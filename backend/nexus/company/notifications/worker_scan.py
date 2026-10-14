"""Bounded source-licensed pending metadata scan; private progress grants no permission."""

import asyncio
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.draft_store import require_draft_time
from nexus.company.notifications.inbox_store import page_ids, recipient_pins, validate_inbox_limit
from nexus.company.notifications.managed_admission import notification_action_id
from nexus.company.notifications.managed_contracts import NativeNotificationSelection
from nexus.company.notifications.qualified_support import require_protection_time
from nexus.company.notifications.worker_config import WorkerConfigurationError
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.notifications.worker_services import (
    GuardedNotificationServices,
    NotificationWorkerServices,
    WorkerSenderAdmission,
)
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import db_now
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.journal_submission import pending_action_record

_UNAVAILABLE = "Notification worker preparation scan is unavailable"


@dataclass(frozen=True, slots=True)
class WorkerPreparationPage:
    candidate: NativeNotificationSelection | None
    processed_after_id: UUID | None
    end_reached: bool


class NotificationPreparationScan:
    def __init__(
        self,
        services: NotificationWorkerServices,
        guard: NotificationOperationGuard,
        guarded: GuardedNotificationServices,
    ) -> None:
        if (
            not isinstance(services, NotificationWorkerServices)
            or not isinstance(guard, NotificationOperationGuard)
            or guarded.preparation.operation_guard is None
            or guarded.preparation.operation_guard.witness is not guard.witness
            or guarded.preparation.operation_guard.snapshot is not guard.snapshot
        ):
            raise WorkerConfigurationError(_UNAVAILABLE)
        self.services, self.guard, self.guarded = services, guard, guarded

    async def page(
        self,
        scope: CompanyControlScope,
        *,
        after_id: UUID | None = None,
        limit: int = 8,
    ) -> WorkerPreparationPage:
        limit = validate_inbox_limit(limit)
        self.guard.require_company(scope.company_id)
        identity = self.guard.witness.identity
        async with (
            asyncio.timeout(30),
            management_owner_transaction(self.services.factory, scope, identity) as (
                session,
                control,
                _,
            ),
        ):
            admitted = await self.services.require_sender_locked(
                session, control, scope, self.guard
            )
            metadata = await page_ids(session, control, scope, after_id, limit)
            current, result = await self._candidates(
                session,
                control,
                scope,
                admitted,
                metadata.rendered_ids,
                metadata.next_after_id is None,
            )
            drafts = self.guarded.drafts
            deadlines = await drafts.qualify_visited_batch_locked(
                session, control, scope, identity, metadata.licensed_ids
            )
            await drafts.qualify_current_batch_locked(session, control, scope, identity, current)
            recipients = await recipient_pins(session, control, scope, metadata.licensed_ids)
            final = await db_now(session)
            require_protection_time(deadlines, final)
            for recipient in recipients:
                drafts.recipients.require_current(recipient, final)
            for draft in current:
                require_draft_time(draft, final)
            admitted.require_time(self.services, final)
            self.services.require_registration(self.guard.snapshot)
            self.guard.require_time(final)
            return result

    async def _candidates(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        admitted: WorkerSenderAdmission,
        ids: tuple[UUID, ...],
        end_reached: bool,
    ) -> tuple[tuple[NotificationDraft, ...], WorkerPreparationPage]:
        current = []
        candidate = None
        processed = None
        for draft_id in ids:
            draft = await self.guarded.drafts.get_current_locked(
                session, control, scope, self.guard.witness.identity, draft_id
            )
            if draft is not None:
                current.append(draft)
                prepared = await self._prepared(session, control, admitted, draft)
                if not prepared and candidate is None:
                    candidate = NativeNotificationSelection(
                        company_id=scope.company_id,
                        draft_id=draft_id,
                        sender_task_id=admitted.binding.child.binding.task_id,
                        plan=admitted.binding.plan,
                    )
                    processed = draft_id
            if candidate is None:
                processed = draft_id
        # Only a fully processed page may complete a cycle; a candidate stops its progress.
        return tuple(current), WorkerPreparationPage(
            candidate, processed, end_reached and candidate is None
        )

    async def _prepared(
        self,
        session: AsyncSession,
        control: CompanyControl,
        admitted: WorkerSenderAdmission,
        draft: NotificationDraft,
    ) -> bool:
        work = admitted.work
        action_id = notification_action_id(admitted.binding.plan, work.task_id, draft.draft_id)
        row = await session.get(JournalAction, action_id)
        intent = await session.get(EffectIntent, (work.company_id, action_id))
        slot = await session.get(NotificationDispatchRow, (work.company_id, draft.draft_id))
        if row is None:
            if intent is not None or slot is not None:
                raise WorkerConfigurationError(_UNAVAILABLE)
            return False
        record = pending_action_record(row)
        expected = self.guarded.preparation._proposal(
            admitted.binding.plan, work, draft, control.policy_version, control.price_version
        )
        if (
            record.proposal != expected
            or action_hash(expected) != row.proposal_hash
            or (row.company_id, row.task_id, row.trace_id)
            != (work.company_id, work.task_id, work.trace_id)
        ):
            raise WorkerConfigurationError(_UNAVAILABLE)
        self._require_issued(intent, slot, admitted, draft, row)
        return True

    @staticmethod
    def _require_issued(
        intent: EffectIntent | None,
        slot: NotificationDispatchRow | None,
        admitted: WorkerSenderAdmission,
        draft: NotificationDraft,
        row: JournalAction,
    ) -> None:
        if intent is None and slot is None:
            return
        if intent is None or slot is None:
            raise WorkerConfigurationError(_UNAVAILABLE)
        work = admitted.work
        actual_intent = (
            intent.task_id,
            intent.trace_id,
            intent.run_id,
            intent.attempt_kind,
            intent.proposal_hash,
            intent.intent_fence,
        )
        expected_intent = (
            work.task_id,
            work.trace_id,
            work.run_id,
            "tool_attempts",
            row.proposal_hash,
            slot.intent_fence,
        )
        actual_slot = (
            slot.action_id,
            slot.task_id,
            slot.trace_id,
            slot.run_id,
            slot.proposal_sha256,
            slot.registration_sha256,
            slot.payload_sha256,
            slot.recipient_policy_sha256,
        )
        expected_slot = (
            row.id,
            work.task_id,
            work.trace_id,
            work.run_id,
            row.proposal_hash,
            work.registration_hash,
            draft.payload_sha256,
            draft.recipient_policy.sha256,
        )
        if actual_intent != expected_intent or actual_slot != expected_slot:
            raise WorkerConfigurationError(_UNAVAILABLE)
