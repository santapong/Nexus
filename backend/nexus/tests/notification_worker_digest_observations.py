"""TEST-only actual digest/event/draft/proposal source bindings and native observations."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.event_models import BrainEvent, BrainEventCursor
from nexus.company.brain.event_store import read_event
from nexus.company.brain.native_fact_contracts import DigestState
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.draft_models import NotificationDraftRow, NotificationEventLinkRow
from nexus.company.notifications.draft_persistence import stored_draft
from nexus.company.notifications.draft_store import owner_scope
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_worker_tick import (
    require_pending_conservation,
)

if TYPE_CHECKING:
    from nexus.tests.notification_worker_digest_fixture import WorkerDigestCase


async def digest_native_counts(factory: async_sessionmaker[AsyncSession]) -> tuple[int, int, int]:
    async with management_owner_transaction(factory, control(), identity(OWNER)) as (session, _, _):
        events = await session.scalar(
            select(func.count()).select_from(BrainEvent).where(BrainEvent.kind == "digest_due")
        )
        drafts = await session.scalar(select(func.count()).select_from(NotificationDraftRow))
        links = await session.scalar(select(func.count()).select_from(NotificationEventLinkRow))
        assert events is not None and drafts is not None and links is not None
        return events, drafts, links


async def require_digest_pins(case: "WorkerDigestCase", draft_id: UUID, action_id: UUID) -> None:
    assert case.window is not None
    services = case.services
    await require_pending_conservation(services.factory, case.native, draft_id, action_id)
    async with management_owner_transaction(services.factory, control(), identity(OWNER)) as (
        session,
        actual,
        _,
    ):
        events = tuple(
            (await session.scalars(select(BrainEvent).where(BrainEvent.kind == "digest_due"))).all()
        )
        assert len(events) == 1
        row = await read_event(session, COMPANY, events[0].event_id)
        assert row is not None
        assert (row.report_id, row.due_bucket, row.scheduled_for) == (
            case.saved.report_id,
            *case.window,
        )
        assert row.notification_policy_sha256 == canonical_sha256(case.registration.policy)
        cursor = await session.get(
            BrainEventCursor, (COMPANY, "nexus.notifications.worker", "native-notification-read-v1")
        )
        assert cursor is not None and cursor.last_sequence == row.sequence
        draft_row = await session.get(NotificationDraftRow, (COMPANY, draft_id))
        assert draft_row is not None
        require_saved_digest_draft(case, stored_draft(draft_row))
        await require_native_digest_frame(session, actual, case, row.event_id)


def require_saved_digest_draft(case: "WorkerDigestCase", draft: NotificationDraft) -> None:
    assert case.window is not None
    assert (draft.kind, draft.due_bucket, draft.scheduled_for) == (
        case.registration.kind,
        *case.window,
    )
    digest = draft.signal.digest
    assert digest is not None and digest.report_id == case.saved.report_id
    assert digest.report_snapshot_sha256 == canonical_sha256(case.saved)
    assert digest.registration_sha256 == canonical_sha256(case.registration)
    assert digest.policy_sha256 == canonical_sha256(case.registration.policy)
    assert draft.signal.source_event.value == case.saved.observed_at.isoformat()
    assert set(case.baseline_references) <= set(draft.provenance.artifacts)
    assert draft.provenance.source_heads == case.saved.data.source_heads


async def require_native_digest_frame(
    session: AsyncSession,
    actual: CompanyControl,
    case: "WorkerDigestCase",
    event_id: UUID,
) -> None:
    wake = await read_event(session, COMPANY, event_id)
    assert wake is not None
    fact = await case.services.drafts.loader.reader.load_event_locked(
        session,
        actual,
        owner_scope(control(), identity(OWNER)),
        identity(OWNER),
        wake,
    )
    assert fact is not None and isinstance(fact.state, DigestState)
    assert fact.state.saved == case.saved and fact.source_recorded_at == case.saved.observed_at
    assert fact.resource == case.registration.resource
    assert set(case.baseline_references) <= set(fact.artifacts)
