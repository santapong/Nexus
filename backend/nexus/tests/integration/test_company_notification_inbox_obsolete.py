"""Licensed resolved native decisions disappear; obsolete status cannot hide lost source access."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from litestar.testing import AsyncTestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.inbox_contracts import NotificationInboxPage
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import JournalAction
from nexus.tests.integration.test_company_api import headers
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_privacy import owner_source
from nexus.tests.notification_inbox_api_support import InboxCase, configured_inbox, inbox_factory

__all__ = ["inbox_factory"]
BASE = f"/api/v2/companies/{COMPANY}/notifications"


async def resolve_first_decision(
    factory: async_sessionmaker[AsyncSession], case: InboxCase, *, index: int = 0
) -> None:
    async with management_owner_transaction(factory, control(), identity(OWNER)) as (session, _, _):
        row = await session.get(JournalAction, case.drafts[index].signal.subject_id)
        assert row is not None
        proposal = ActionProposal.model_validate_json(row.proposal_json)
    await CompanyJournal(factory).approve_registered(
        LedgerScope(
            company_id=COMPANY,
            principal_id=OWNER,
            task_id=proposal.task_id,
            trace_id=proposal.trace_id,
        ),
        proposal.action_id,
        action_hash(proposal),
        datetime.now(UTC),
        identity=identity(OWNER),
    )


async def test_resolved_decision_skips_its_body_and_keeps_other_current_notice(
    inbox_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await configured_inbox(inbox_factory, tmp_path)
    await resolve_first_decision(inbox_factory, case)
    async with AsyncTestClient(case.app) as client:
        response = await client.get(BASE, headers=headers(OWNER))
        assert response.status_code == 200
        page = NotificationInboxPage.model_validate_json(response.content)
        assert tuple(item.draft.draft_id for item in page.notifications) == (
            case.drafts[1].draft_id,
        )
        assert case.drafts[0].payload.text not in response.text
        resolved_detail = await client.get(
            f"{BASE}/{case.drafts[0].draft_id}", headers=headers(OWNER)
        )
        assert resolved_detail.status_code == 404


async def test_actual_resolved_decision_does_not_bypass_complete_source_licensing(
    inbox_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await configured_inbox(inbox_factory, tmp_path)
    await resolve_first_decision(inbox_factory, case)
    await owner_source(inbox_factory, active=False)
    async with AsyncTestClient(case.app) as client:
        response = await client.get(BASE, headers=headers(OWNER))
        assert response.status_code in {403, 404}
        assert "notifications" not in response.json() and "example.invalid" not in response.text


async def test_licensed_obsolete_visit_advances_bounded_cursor_to_current_notice(
    inbox_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await configured_inbox(inbox_factory, tmp_path)
    await resolve_first_decision(inbox_factory, case, index=1)
    async with AsyncTestClient(case.app) as client:
        first = await client.get(BASE, params={"limit": 1}, headers=headers(OWNER))
        assert first.status_code == 200
        empty = NotificationInboxPage.model_validate_json(first.content)
        assert empty.notifications == () and empty.next_after_id == case.drafts[1].draft_id
        second = await client.get(
            BASE, params={"limit": 1, "after_id": str(empty.next_after_id)}, headers=headers(OWNER)
        )
        assert second.status_code == 200
        current = NotificationInboxPage.model_validate_json(second.content)
        assert tuple(item.draft.draft_id for item in current.notifications) == (
            case.drafts[0].draft_id,
        )
        assert current.next_after_id is None
