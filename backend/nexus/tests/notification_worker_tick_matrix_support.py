"""TEST-only controls and actual read-only conservation; no permission, clock or cursor edits."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.native_fact_contracts import DecisionSelector
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.draft_store import owner_scope
from nexus.company.notifications.worker_contracts import NotificationWorkerRegistrationFile
from nexus.company.notifications.worker_services import NotificationWorkerServices
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.harness.journal_models import CostHold, JournalAction
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_worker_tick import publication_counts
from nexus.tests.notification_worker_tick_fixture import WorkerTickNativeCase, source_pending


@dataclass(frozen=True)
class TickLedger:
    publication: tuple[int, int, int, int, int | None, int]
    journal_ids: tuple[UUID, ...]
    journal_state_sha256: str
    effects: tuple[int, ...]
    counters: tuple[tuple[UUID, int, int], ...]

    def require_no_effects(self) -> None:
        assert self.effects == (0, 0, 0, 0, 0)
        assert len(self.counters) == 5
        assert all(model == tool == 0 for _, model, tool in self.counters)


def configure_worker(
    root: Path,
    *,
    emit: bool,
    consume: bool,
    prepare: bool,
    max_candidates: int = 8,
) -> None:
    path = root / "synthetic-tick-registration.json"
    value = NotificationWorkerRegistrationFile.model_validate_json(path.read_bytes())
    changed = value.model_copy(
        update={
            "configuration": value.configuration.model_copy(
                update={
                    "emit_fallback": emit,
                    "consume_events": consume,
                    "prepare_pending": prepare,
                    "max_candidates": max_candidates,
                }
            )
        }
    )
    checked = NotificationWorkerRegistrationFile.model_validate_json(changed.model_dump_json())
    assert checked.registration == value.registration
    path.write_text(checked.model_dump_json())
    path.chmod(0o600)


async def tick_ledger(factory: async_sessionmaker[AsyncSession]) -> TickLedger:
    publication = await publication_counts(factory)
    async with management_owner_transaction(factory, control(), identity(OWNER)) as (session, _, _):
        rows = tuple(
            (await session.scalars(select(JournalAction).order_by(JournalAction.id))).all()
        )
        material = [
            (str(row.id), row.state, row.proposal_hash, row.approval_json, row.consumed_at)
            for row in rows
        ]
        assert all(row.approval_json is None and row.consumed_at is None for row in rows)
        effects = []
        for table in (
            CostHold,
            EffectIntent,
            NotificationDispatchRow,
            SegmentDispatch,
            ExecutionAttempt,
        ):
            count = await session.scalar(select(func.count()).select_from(table))
            assert count is not None
            effects.append(count)
        works = tuple(
            (await session.scalars(select(ExecutionWork).order_by(ExecutionWork.task_id))).all()
        )
        counters = tuple(
            (row.task_id, row.model_requests_used, row.tool_attempts_used) for row in works
        )
        return TickLedger(
            publication,
            tuple(row.id for row in rows),
            hashlib.sha256(json.dumps(material, default=str).encode()).hexdigest(),
            tuple(effects),
            counters,
        )


async def emit_decision(services: NotificationWorkerServices, action_id: UUID) -> UUID:
    bound = services.registrations.snapshot().value.registration.sender
    witness = await services.identities.current(expected_binding=bound)
    event = await NativeFactEmitter(services.factory, NativeFactReader(services.facts)).emit(
        owner_scope(control(), witness.identity),
        witness.identity,
        DecisionSelector(company_id=COMPANY, action_id=action_id),
    )
    assert event is not None
    return event.event_id


async def three_pending_sources(
    factory: async_sessionmaker[AsyncSession],
    case: WorkerTickNativeCase,
    services: NotificationWorkerServices,
) -> tuple[ActionProposal, ...]:
    actions = [case.source_action]
    for _ in range(2):
        action, _ = await source_pending(factory, case.source)
        actions.append(action)
    assert len({row.action_id for row in actions}) == 3
    for action in actions:
        assert action.task_id != case.notification.children[0].binding.task_id
        await emit_decision(services, action.action_id)
    return tuple(actions)
