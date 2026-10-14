"""A separate mechanical decision source stages pending review without effects."""

from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.event_models import BrainEvent, BrainEventCursor
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.draft_models import NotificationDraftRow, NotificationEventLinkRow
from nexus.company.notifications.proposals import NotificationDispatchParameters
from nexus.company.notifications.worker_tick import NotificationReadPreparationWorker
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CostHold, JournalAction
from nexus.harness.lifecycle import ActionState
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_worker_tick_fixture import (
    WorkerTickNativeCase,
    worker_tick_factory,
    worker_tick_native_case,
)
from nexus.tests.notification_worker_tick_services_fixture import configured_tick_services

__all__ = ["worker_tick_factory"]


async def publication_counts(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[int, int, int, int, int | None, int]:
    async with management_owner_transaction(factory, control(), identity(OWNER)) as (session, _, _):
        total = await session.scalar(select(func.count()).select_from(BrainEvent))
        decision = await session.scalar(
            select(func.count())
            .select_from(BrainEvent)
            .where(BrainEvent.kind == "decision_required")
        )
        links = await session.scalar(select(func.count()).select_from(NotificationEventLinkRow))
        drafts = await session.scalar(select(func.count()).select_from(NotificationDraftRow))
        cursor = await session.get(
            BrainEventCursor, (COMPANY, "nexus.notifications.worker", "native-notification-read-v1")
        )
        sequence = await session.scalar(select(func.max(BrainEvent.sequence)))
        assert (
            total is not None and decision is not None and links is not None and drafts is not None
        )
        return (
            total,
            decision,
            links,
            drafts,
            cursor.last_sequence if cursor else None,
            sequence or 0,
        )


async def require_pending_conservation(
    factory: async_sessionmaker[AsyncSession],
    case: WorkerTickNativeCase,
    draft_id: UUID,
    action_id: UUID,
) -> None:
    async with management_owner_transaction(factory, control(), identity(OWNER)) as (session, _, _):
        for current_id in (case.source_action.action_id, action_id):
            row = await session.get(JournalAction, current_id)
            assert row is not None and row.state == ActionState.AWAITING_APPROVAL.value
            assert row.approval_json is None and row.consumed_at is None
        draft = await session.get(NotificationDraftRow, (COMPANY, draft_id))
        action = await session.get(JournalAction, action_id)
        assert draft is not None and action is not None
        proposed = ActionProposal.model_validate_json(action.proposal_json)
        sender = case.notification.children[0].binding
        assert (proposed.task_id, proposed.trace_id, proposed.actor_id) == (
            sender.task_id,
            sender.trace_id,
            sender.actor_id,
        )
        assert proposed.parameters == NotificationDispatchParameters(
            draft_id=draft_id,
            payload_sha256=draft.payload_sha256,
            recipient_policy_sha256=draft.recipient_policy_sha256,
        ).model_dump(mode="json")
        for table in (CostHold, EffectIntent, NotificationDispatchRow):
            assert await session.scalar(select(func.count()).select_from(table)) == 0
        works = tuple(
            (
                await session.scalars(
                    select(ExecutionWork).where(ExecutionWork.company_id == COMPANY)
                )
            ).all()
        )
        assert len(works) == 5
        assert all(row.model_requests_used == row.tool_attempts_used == 0 for row in works)


async def test_distinct_native_source_tick_prepares_exact_pending_without_effects(
    worker_tick_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await worker_tick_native_case(worker_tick_factory, tmp_path / "blobs")
    services = await configured_tick_services(worker_tick_factory, tmp_path, case)
    worker = NotificationReadPreparationWorker(services, enabled=True)
    before = await publication_counts(worker_tick_factory)
    first = await worker.tick()
    assert first.disposition == "staged" and first.new_wakes == 1
    assert len(first.draft_ids) == len(first.action_ids) == 1
    assert first.action_ids[0] != case.source_action.action_id
    published = await publication_counts(worker_tick_factory)
    assert published[:4] == tuple(value + 1 for value in before[:4])
    assert published[4] == published[5]
    second = await worker.tick()
    assert second.disposition == "quiet" and second.new_wakes == 0
    assert second.replayed_wakes == 1 and not second.draft_ids and not second.action_ids
    assert await publication_counts(worker_tick_factory) == published
    await require_pending_conservation(
        worker_tick_factory, case, first.draft_ids[0], first.action_ids[0]
    )
    assert case.catalog.models.models == () and case.notification.goal != case.source.goal
