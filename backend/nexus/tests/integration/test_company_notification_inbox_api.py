"""Actual signed owner HTTP discovers only bounded currently qualified native inbox bodies."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.notifications.inbox_contracts import (
    NotificationInboxEntry,
    NotificationInboxPage,
)
from nexus.tests.integration.test_company_api import headers
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER
from nexus.tests.notification_inbox_api_support import configured_inbox, inbox_factory

__all__ = ["inbox_factory"]
BASE = f"/api/v2/companies/{COMPANY}/notifications"


async def test_actual_owner_list_detail_scoped_cursor_and_native_schema(
    inbox_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await configured_inbox(inbox_factory, tmp_path)
    expected = tuple(sorted(case.drafts, key=lambda d: (d.recorded_at, d.draft_id), reverse=True))
    async with AsyncTestClient(case.app) as client:
        page = await client.get(BASE, params={"limit": 1}, headers=headers(OWNER))
        assert page.status_code == 200
        parsed = NotificationInboxPage.model_validate_json(page.content)
        assert parsed.notifications[0].draft == expected[0]
        assert parsed.next_after_id == expected[0].draft_id
        assert parsed.notifications[0].latest_submission is None
        next_page = await client.get(
            BASE, params={"limit": 1, "after_id": str(parsed.next_after_id)}, headers=headers(OWNER)
        )
        assert next_page.status_code == 200
        latter = NotificationInboxPage.model_validate_json(next_page.content)
        assert tuple(item.draft for item in latter.notifications) == (expected[1],)
        assert latter.next_after_id is None
        detail = await client.get(f"{BASE}/{expected[1].draft_id}", headers=headers(OWNER))
        assert detail.status_code == 200
        assert NotificationInboxEntry.model_validate_json(detail.content).draft == expected[1]
        member = await client.get(BASE, headers=headers(ACTOR))
        assert member.status_code == 403 and "native" not in member.text.lower()
        absent = await client.get(f"{BASE}/{uuid4()}", headers=headers(OWNER))
        assert absent.status_code == 404 and "payload" not in absent.text
        foreign = await client.get(
            f"/api/v2/companies/{UUID(int=99)}/notifications", headers=headers(OWNER)
        )
        assert foreign.status_code == 403


@pytest.mark.parametrize("mode", ["unmounted", "unconfigured"])
async def test_explicit_optional_inbox_no_default_store(
    inbox_factory: async_sessionmaker[AsyncSession], tmp_path: Path, mode: str
) -> None:
    case = await configured_inbox(inbox_factory, tmp_path, mount=mode != "unmounted", enabled=False)
    async with AsyncTestClient(case.app) as client:
        response = await client.get(BASE, headers=headers(OWNER))
        assert response.status_code == (404 if mode == "unmounted" else 503)


async def test_cursor_and_limit_bounds_are_safe_requests_not_authority(
    inbox_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await configured_inbox(inbox_factory, tmp_path)
    async with AsyncTestClient(case.app) as client:
        for limit in (0, -1, 9):
            result = await client.get(BASE, params={"limit": limit}, headers=headers(OWNER))
            assert result.status_code == 422 and "payload" not in result.text
        bad_cursor = await client.get(
            BASE, params={"after_id": str(uuid4())}, headers=headers(OWNER)
        )
        assert bad_cursor.status_code == 404 and "payload" not in bad_cursor.text
        invalid_uuid = await client.get(
            BASE, params={"after_id": "not-a-uuid"}, headers=headers(OWNER)
        )
        assert invalid_uuid.status_code == 422
