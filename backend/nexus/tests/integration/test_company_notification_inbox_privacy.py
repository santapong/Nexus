"""Current native source/recipient/member loss never returns partial owner inbox bodies."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.api import company_notification_routes
from nexus.api.company_routes import CompanyRequest
from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.notifications.api_services import NotificationApiServices
from nexus.company.notifications.contracts import NotificationDraft
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.test_company_api import headers
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_notification_privacy import owner_source
from nexus.tests.notification_inbox_api_support import configured_inbox, inbox_factory

__all__ = ["inbox_factory"]
BASE = f"/api/v2/companies/{COMPANY}/notifications"


@pytest.mark.parametrize("loss", ["source", "recipient"])
async def test_actual_source_or_recipient_revoke_hides_page_and_detail(
    inbox_factory: async_sessionmaker[AsyncSession], tmp_path: Path, loss: str
) -> None:
    case = await configured_inbox(inbox_factory, tmp_path)
    if loss == "source":
        await owner_source(inbox_factory, active=False)
    else:
        case.recipient_path.unlink()
    async with AsyncTestClient(case.app) as client:
        for url in (BASE, f"{BASE}/{case.drafts[0].draft_id}"):
            response = await client.get(url, headers=headers(OWNER))
            assert response.status_code in {403, 404}
            assert "notifications" not in response.json() and "draft" not in response.json()
            assert case.drafts[0].payload.text not in response.text
            assert "example.invalid" not in response.text


async def test_current_owner_revoked_after_signed_directory_lookup_denies_all_body(
    inbox_factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = await configured_inbox(inbox_factory, tmp_path)
    original = company_notification_routes.notification_owner

    async def revoke(
        request: CompanyRequest, services: NotificationApiServices, company_id: UUID
    ) -> tuple[CompanyControlScope, VerifiedIdentity]:
        result = await original(request, services, company_id)
        await PersistentCompanyDirectory(inbox_factory).set_membership(
            MembershipChange(
                company_id=COMPANY, principal_id=OWNER, role="owner", membership_active=False
            ),
            control(),
        )
        return result

    monkeypatch.setattr(company_notification_routes, "notification_owner", revoke)
    async with AsyncTestClient(case.app) as client:
        response = await client.get(BASE, headers=headers(OWNER))
        assert response.status_code == 403 and "notifications" not in response.json()
        assert "example.invalid" not in response.text


@pytest.mark.parametrize("expiry", ["source", "recipient"])
async def test_whole_page_final_await_expiry_hides_every_body(
    inbox_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expiry: str,
) -> None:
    case = await configured_inbox(inbox_factory, tmp_path, expiry=expiry)
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
        assert len(drafts) == 2
        reached = True
        for _ in range(42):
            if await db_now(session) >= deadline:
                break
            await session.execute(select(func.pg_sleep(0.5)))
        assert await db_now(session) >= deadline

    monkeypatch.setattr(case.store, "qualify_current_batch_locked", delayed)
    async with AsyncTestClient(case.app) as client:
        response = await client.get(BASE, headers=headers(OWNER))
        assert reached and response.status_code in {403, 404}
        assert "notifications" not in response.json()
        for draft in case.drafts:
            assert draft.payload.text not in response.text
        assert "example.invalid" not in response.text
