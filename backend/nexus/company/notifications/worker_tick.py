"""Opt-in bounded native publication/preparation; never approve, allocate, dispatch or poll."""

import asyncio
from uuid import UUID, uuid4

from sqlalchemy import func, select

from nexus.company.access import CompanyControlScope
from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.native_fact_contracts import DecisionState
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.draft_store import owner_scope
from nexus.company.notifications.proposals import NOTIFICATION_TOOL
from nexus.company.notifications.worker_config import WorkerConfigurationError
from nexus.company.notifications.worker_consumer import WorkerSenderFinalGuard
from nexus.company.notifications.worker_contracts import WorkerTickResult
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.notifications.worker_scan import NotificationPreparationScan
from nexus.company.notifications.worker_services import (
    GuardedNotificationServices,
    NotificationWorkerServices,
)

_UNAVAILABLE = "Notification worker tick is unavailable"
_DISABLED = WorkerTickResult(disposition="disabled")


class NotificationReadPreparationWorker:
    def __init__(self, services: NotificationWorkerServices, *, enabled: bool = False) -> None:
        if type(enabled) is not bool or not isinstance(services, NotificationWorkerServices):
            raise WorkerConfigurationError(_UNAVAILABLE)
        self.services, self.enabled = services, enabled
        self._scan_after: UUID | None = None
        self._snapshot_sha: str | None = None

    async def tick(self) -> WorkerTickResult:
        if not self.enabled:
            return _DISABLED
        snapshot = self.services.registrations.snapshot()
        config = snapshot.value.configuration
        if not config.enabled:
            return _DISABLED
        self.services.require_registration(snapshot)
        if snapshot.sha256 != self._snapshot_sha:
            self._scan_after, self._snapshot_sha = None, snapshot.sha256
        async with asyncio.timeout(config.timeout_seconds):
            witness = await self.services.identities.current(
                expected_binding=snapshot.value.registration.sender
            )
            guard = NotificationOperationGuard(witness, snapshot, self.services.registrations)
            guarded = self.services.guarded(guard)
            scope = CompanyControlScope(
                company_id=guard.registration.company_id,
                principal_id=witness.identity.principal_id,
                operation_id=uuid4(),
                trace_id=uuid4(),
            )
            new, replayed = await self._emit(scope, guard) if config.emit_fallback else (0, 0)
            draft_ids: tuple[UUID, ...] = ()
            acknowledged = 0
            if config.consume_events:
                consumed = await guarded.consumer.consume(
                    scope, witness.identity, max_events=config.max_events
                )
                acknowledged = len(consumed.publications)
                draft_ids = tuple(
                    row.draft.draft_id
                    for row in consumed.publications
                    if row.state == "published" and row.draft is not None
                )
            action_ids = (
                await self._prepare(scope, guard, guarded, config.max_candidates)
                if config.prepare_pending
                else ()
            )
            return WorkerTickResult(
                disposition="staged" if new or draft_ids or action_ids else "quiet",
                new_wakes=new,
                replayed_wakes=replayed,
                events_acknowledged=acknowledged,
                draft_ids=draft_ids,
                action_ids=action_ids,
            )

    async def _emit(
        self,
        scope: CompanyControlScope,
        guard: NotificationOperationGuard,
    ) -> tuple[int, int]:
        new, replayed = 0, 0
        identity, brain = guard.witness.identity, owner_scope(scope, guard.witness.identity)
        for subject in guard.registration.subjects:
            async with management_owner_transaction(self.services.factory, scope, identity) as (
                session,
                control,
                _,
            ):
                admitted = await self.services.require_sender_locked(session, control, scope, guard)
                final_guard = WorkerSenderFinalGuard(guard, self.services)
                final_guard.capture(admitted)
                reader = NativeFactReader(self.services.facts)
                fact = await reader.load_locked(session, control, brain, identity, subject.selector)
                if fact is not None and fact.resource != subject.resource:
                    raise WorkerConfigurationError(_UNAVAILABLE)
                if (
                    fact is not None
                    and isinstance(fact.state, DecisionState)
                    and (
                        fact.state.work.task_id == guard.registration.sender.task_id
                        or fact.state.action.proposal.tool == NOTIFICATION_TOOL
                    )
                ):
                    raise WorkerConfigurationError(_UNAVAILABLE)
                before = await session.scalar(
                    select(func.max(BrainEvent.sequence)).where(
                        BrainEvent.company_id == scope.company_id
                    )
                )
                event = await NativeFactEmitter(
                    self.services.factory, reader, operation_guard=final_guard
                ).emit_locked(
                    session,
                    control,
                    brain,
                    identity,
                    subject.selector,
                )
                is_new = event is not None and event.sequence > (before or 0)
                is_replay = event is not None and not is_new
            new += int(is_new)
            replayed += int(is_replay)
        return new, replayed

    async def _prepare(
        self,
        scope: CompanyControlScope,
        guard: NotificationOperationGuard,
        guarded: GuardedNotificationServices,
        limit: int,
    ) -> tuple[UUID, ...]:
        page = await NotificationPreparationScan(self.services, guard, guarded).page(
            scope,
            after_id=self._scan_after,
            limit=limit,
        )
        result: tuple[UUID, ...] = ()
        if page.candidate is not None:
            await guarded.preparation.prepare(scope, guard.witness.identity, page.candidate)
            if guarded.preparation.created_action_id is not None:
                result = (guarded.preparation.created_action_id,)
        self._scan_after = None if page.end_reached else page.processed_after_id
        return result
