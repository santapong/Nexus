"""Paused owner audit remains read-only; expired or incorrectly signed JWT never reveals inbox."""

from __future__ import annotations

import time
from pathlib import Path

import jwt
from litestar.testing import AsyncTestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.control_store import CompanyControls
from nexus.company.notifications.inbox_contracts import NotificationInboxPage
from nexus.tests.integration.test_company_api import KEY, headers
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, WORKSPACE, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_inbox_api_support import configured_inbox, inbox_factory

__all__ = ["inbox_factory"]
BASE = f"/api/v2/companies/{COMPANY}/notifications"


async def test_real_signed_owner_paused_read_and_invalid_token_denial(
    inbox_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await configured_inbox(inbox_factory, tmp_path)
    await CompanyControls(inbox_factory).set_paused_registered(control(), identity(OWNER), True)
    now = int(time.time())
    expired = jwt.encode(
        {"sub": str(OWNER), "workspace_id": str(WORKSPACE), "iat": now - 120, "exp": now - 60},
        KEY,
        algorithm="HS256",
    )
    async with AsyncTestClient(case.app) as client:
        paused = await client.get(BASE, headers=headers(OWNER))
        assert paused.status_code == 200
        assert len(NotificationInboxPage.model_validate_json(paused.content).notifications) == 2
        for authentication in (
            {"authorization": f"Bearer {expired}"},
            headers(OWNER, key="wrong-fixture-key-with-at-least-32chars"),
            {},
        ):
            denied = await client.get(BASE, headers=authentication)
            assert denied.status_code == 401
            assert "notifications" not in denied.json() and "example.invalid" not in denied.text
