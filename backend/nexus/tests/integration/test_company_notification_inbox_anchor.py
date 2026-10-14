"""Every queried anchor is licensed, including an otherwise empty current inbox page."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.inbox_contracts import NotificationInboxPage
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.test_company_api import headers
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_notification_privacy import owner_source
from nexus.tests.notification_inbox_api_support import configured_inbox, inbox_factory

__all__ = ["inbox_factory"]
BASE = f"/api/v2/companies/{COMPANY}/notifications"


async def test_revoked_oldest_cursor_anchor_cannot_return_unlicensed_empty_page(
    inbox_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await configured_inbox(inbox_factory, tmp_path)
    oldest = min(case.drafts, key=lambda d: (d.recorded_at, d.draft_id))
    await owner_source(inbox_factory, active=False)
    async with AsyncTestClient(case.app) as client:
        response = await client.get(
            BASE, params={"after_id": str(oldest.draft_id), "limit": 8}, headers=headers(OWNER)
        )
        assert response.status_code in {403, 404}
        assert "notifications" not in response.json() and "example.invalid" not in response.text


async def test_cursor_plus_eight_candidate_scan_is_nine_licenses_and_may_end_in_empty_page(
    inbox_factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = await configured_inbox(inbox_factory, tmp_path, draft_count=9)
    expected = sorted(case.drafts, key=lambda d: (d.recorded_at, d.draft_id), reverse=True)
    original = case.store.qualify_visited_batch_locked
    calls: list[tuple[UUID, ...]] = []

    async def observed(
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        actor: VerifiedIdentity,
        ids: tuple[UUID, ...],
    ) -> tuple[datetime, ...]:
        calls.append(ids)
        return await original(session, control, scope, actor, ids)

    monkeypatch.setattr(case.store, "qualify_visited_batch_locked", observed)
    async with AsyncTestClient(case.app) as client:
        page = await client.get(
            BASE, params={"after_id": str(expected[0].draft_id), "limit": 8}, headers=headers(OWNER)
        )
        assert page.status_code == 200
        parsed = NotificationInboxPage.model_validate_json(page.content)
        assert tuple(item.draft.draft_id for item in parsed.notifications) == tuple(
            d.draft_id for d in expected[1:]
        )
        assert len(calls[0]) == 9 and calls[0][0] == expected[0].draft_id
        assert parsed.next_after_id == expected[-1].draft_id
        empty = await client.get(
            BASE, params={"after_id": str(parsed.next_after_id), "limit": 8}, headers=headers(OWNER)
        )
        assert empty.status_code == 200
        final = NotificationInboxPage.model_validate_json(empty.content)
        assert final.notifications == () and final.next_after_id is None
        assert calls[-1] == (expected[-1].draft_id,)


@pytest.mark.parametrize("expiry", ["source", "recipient"])
async def test_empty_cursor_page_final_await_expiry_still_hides_licensed_anchor(
    inbox_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expiry: str,
) -> None:
    case = await configured_inbox(inbox_factory, tmp_path, expiry=expiry)
    oldest = min(case.drafts, key=lambda d: (d.recorded_at, d.draft_id))
    deadline = case.deadline
    assert deadline is not None
    original = case.store.qualify_current_batch_locked
    reached = False

    async def delayed(
        session: AsyncSession,
        current: CompanyControl,
        scope: CompanyControlScope,
        actor: VerifiedIdentity,
        drafts: tuple[NotificationDraft, ...],
    ) -> None:
        nonlocal reached
        await original(session, current, scope, actor, drafts)
        assert drafts == ()
        reached = True
        for _ in range(42):
            if await db_now(session) >= deadline:
                break
            await session.execute(select(func.pg_sleep(0.5)))
        assert await db_now(session) >= deadline

    monkeypatch.setattr(case.store, "qualify_current_batch_locked", delayed)
    async with AsyncTestClient(case.app) as client:
        response = await client.get(
            BASE, params={"after_id": str(oldest.draft_id), "limit": 8}, headers=headers(OWNER)
        )
        assert reached and response.status_code in {403, 404}
        assert "notifications" not in response.json()
        assert oldest.payload.text not in response.text
