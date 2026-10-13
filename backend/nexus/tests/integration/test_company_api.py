"""Actual signed Litestar HTTP against a restricted private PostgreSQL company profile."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from uuid import UUID

import jwt
import pytest
from litestar.testing import AsyncTestClient
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.company.access import PrincipalAccess, VerifiedIdentity
from nexus.company.control_store import CompanyControls
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_models import CompanyControl, CostHold
from nexus.settings import settings
from nexus.tests.integration.test_company_controls import bootstrap
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    TASK,
    TRACE,
    WORKSPACE,
    control,
    migrate,
)
from nexus.tests.integration.test_company_registered_authorization import pending, prepare, scope

KEY = "http-fixture-key-with-at-least-32-characters"
BASE = f"/api/v2/companies/{COMPANY}/work/{TASK}"


def headers(
    principal: UUID = ACTOR, workspace: UUID = WORKSPACE, *, key: str = KEY
) -> dict[str, str]:
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": str(principal),
            "workspace_id": str(workspace),
            "iat": now,
            "exp": now + 300,
            "role": "owner",
            "company_id": str(UUID(int=99)),
        },
        key,
        algorithm="HS256",
    )
    return {"authorization": f"Bearer {token}"}


@pytest.fixture
async def api_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    monkeypatch.setattr(settings, "jwt_secret_key", KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    monkeypatch.setattr(settings, "personal_mode", True)
    if not settings.company_test_database_url:
        pytest.skip("explicit private company API test DB is not configured")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_api"
    assert settings.company_test_database_url != settings.database_url
    engine = create_async_engine(url)
    # Litestar's AsyncTestClient runs ASGI through a blocking portal/event loop.
    # Setup and request transactions therefore cannot share asyncpg connections.
    app = create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(migrate, "upgrade")
    try:
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        async with engine.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await engine.dispose()


async def test_http_reads_use_signed_workspace_current_role_and_exact_work_trace(
    api_factory: async_sessionmaker[AsyncSession],
) -> None:
    journal, directory = await prepare(api_factory)
    action = await pending(journal)
    aggregate = CompanyServices(directory, journal, CompanyControls(api_factory))
    async with AsyncTestClient(create_company_app(aggregate)) as client:
        current = await client.get("/api/v2/company", headers=headers())
        assert current.status_code == 200 and current.json()["company_id"] == str(COMPANY)
        assert current.json()["membership_role"] == "member"
        work = await client.get(BASE, params={"trace_id": str(TRACE)}, headers=headers())
        assert work.status_code == 200 and work.json()["actor_id"] == str(ACTOR)
        read = await client.get(
            f"{BASE}/actions/{action.action_id}",
            params={"trace_id": str(TRACE)},
            headers=headers(OWNER),
        )
        assert read.status_code == 200 and read.json()["proposal"]["task_id"] == str(TASK)
        wrong = await client.get(BASE, params={"trace_id": str(UUID(int=99))}, headers=headers())
        assert wrong.status_code == 403
        foreign = await client.get(
            f"/api/v2/companies/{UUID(int=99)}/work/{TASK}",
            params={"trace_id": str(TRACE)},
            headers=headers(),
        )
        assert foreign.status_code == 403


@pytest.mark.parametrize("invalid", ["missing", "signature", "workspace", "principal", "inactive"])
async def test_http_authentication_and_current_membership_have_no_personal_fallback(
    api_factory: async_sessionmaker[AsyncSession],
    invalid: str,
) -> None:
    journal, directory = await prepare(api_factory)
    expected, auth = 403, headers()
    if invalid == "missing":
        expected, auth = 401, {}
    if invalid == "signature":
        expected, auth = 401, headers(key="wrong-fixture-signing-key-at-least-32-bytes")
    if invalid == "workspace":
        auth = headers(workspace=UUID(int=99))
    if invalid == "principal":
        auth = headers(UUID(int=99))
    if invalid == "inactive":
        await directory.set_membership(
            MembershipChange(
                company_id=COMPANY, principal_id=ACTOR, role="member", membership_active=False
            ),
            control(),
        )
    async with AsyncTestClient(
        create_company_app(CompanyServices(directory, journal, CompanyControls(api_factory)))
    ) as client:
        response = await client.get("/api/v2/company", headers=auth)
        assert response.status_code == expected


async def test_http_owner_decision_saves_exact_decision_without_scheduling_or_effect(
    api_factory: async_sessionmaker[AsyncSession],
) -> None:
    journal, directory = await prepare(api_factory)
    action = await pending(journal, decision=False)
    path = f"{BASE}/actions/{action.action_id}/decision"
    body = {"trace_id": str(TRACE), "expected_hash": action_hash(action), "approved": True}
    async with AsyncTestClient(
        create_company_app(CompanyServices(directory, journal, CompanyControls(api_factory)))
    ) as client:
        denied = await client.post(path, json=body, headers=headers())
        assert denied.status_code == 403
        stale = await client.post(
            path, json=body | {"expected_hash": "0" * 64}, headers=headers(OWNER)
        )
        assert stale.status_code == 409
        accepted = await client.post(path, json=body, headers=headers(OWNER))
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "decision_saved"
        assert accepted.json()["scheduled"] is False and accepted.json()["executed"] is False
        record = await journal.get_action(scope(), action.action_id)
        assert record.approval is not None and record.approval.approver_id == OWNER
        assert record.consumed_at is None
    async with api_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert (await session.scalars(select(CostHold))).all() == []


@pytest.mark.parametrize(
    "extra",
    [{"actor_id": str(OWNER)}, {"work_cap_usd": "99"}, {"approved": "true"}, {"approved": 1}],
)
async def test_http_decision_body_rejects_scope_spoofing_and_nonbool(
    api_factory: async_sessionmaker[AsyncSession],
    extra: dict[str, object],
) -> None:
    journal, directory = await prepare(api_factory)
    action = await pending(journal, decision=False)
    body: dict[str, object] = {
        "trace_id": str(TRACE),
        "expected_hash": action_hash(action),
        "approved": True,
    }
    async with AsyncTestClient(
        create_company_app(CompanyServices(directory, journal, CompanyControls(api_factory)))
    ) as client:
        response = await client.post(
            f"{BASE}/actions/{action.action_id}/decision", json=body | extra, headers=headers(OWNER)
        )
        assert response.status_code == 422
    assert (await journal.get_action(scope(), action.action_id)).approval is None


async def test_http_owner_pause_rejects_member_and_persists_without_minting_work(
    api_factory: async_sessionmaker[AsyncSession],
) -> None:
    journal, directory = await prepare(api_factory)
    path = f"/api/v2/companies/{COMPANY}/pause"
    async with AsyncTestClient(
        create_company_app(CompanyServices(directory, journal, CompanyControls(api_factory)))
    ) as client:
        denied = await client.post(path, json={"paused": True}, headers=headers())
        assert denied.status_code == 403
        malformed = await client.post(path, json={"paused": "false"}, headers=headers(OWNER))
        assert malformed.status_code == 422
        response = await client.post(path, json={"paused": True}, headers=headers(OWNER))
        assert response.status_code == 200 and response.json()["paused"] is True
        assert response.json()["operation_id"] != str(TASK)
    async with api_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        current = await session.get(CompanyControl, COMPANY)
        assert current is not None and current.paused


class RevokingDirectory(PersistentCompanyDirectory):
    """Inject a real DB revocation after the real initial lookup to force an HTTP race."""

    async def lookup_principal(
        self, identity: VerifiedIdentity, *, task_id: UUID, trace_id: UUID
    ) -> PrincipalAccess | None:
        access = await super().lookup_principal(identity, task_id=task_id, trace_id=trace_id)
        if access is not None and identity.principal_id == OWNER:
            await self.set_membership(
                MembershipChange(
                    company_id=COMPANY, principal_id=OWNER, role="owner", membership_active=False
                ),
                control(),
            )
        return access


async def test_http_pause_rechecks_owner_after_gateway_race_with_real_db_revocation(
    api_factory: async_sessionmaker[AsyncSession],
) -> None:
    journal, _ = await prepare(api_factory)
    directory = RevokingDirectory(api_factory)
    async with AsyncTestClient(
        create_company_app(CompanyServices(directory, journal, CompanyControls(api_factory)))
    ) as client:
        response = await client.post(
            f"/api/v2/companies/{COMPANY}/pause", json={"paused": True}, headers=headers(OWNER)
        )
        assert response.status_code == 403
    async with api_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        current = await session.get(CompanyControl, COMPANY)
        assert current is not None and not current.paused


async def test_http_action_read_rejects_legacy_snapshot_with_another_trace(
    api_factory: async_sessionmaker[AsyncSession],
) -> None:
    journal, directory = await prepare(api_factory)
    original = await pending(journal)
    bad = original.model_validate(
        original.model_dump() | {"action_id": UUID(int=101), "trace_id": UUID(int=99)}
    )
    await journal.submit(bad, scope().model_copy(update={"trace_id": UUID(int=99)}))
    async with AsyncTestClient(
        create_company_app(CompanyServices(directory, journal, CompanyControls(api_factory)))
    ) as client:
        response = await client.get(
            f"{BASE}/actions/{bad.action_id}",
            params={"trace_id": str(TRACE)},
            headers=headers(OWNER),
        )
        assert response.status_code == 404


async def test_http_owner_pause_does_not_require_registered_work(
    api_factory: async_sessionmaker[AsyncSession],
) -> None:
    directory = await bootstrap(api_factory)
    aggregate = CompanyServices(
        directory, CompanyJournal(api_factory), CompanyControls(api_factory)
    )
    async with AsyncTestClient(create_company_app(aggregate)) as client:
        response = await client.post(
            f"/api/v2/companies/{COMPANY}/pause", json={"paused": True}, headers=headers(OWNER)
        )
        assert response.status_code == 200 and response.json()["paused"] is True


async def test_http_owner_audits_inactive_work_while_actor_and_decisions_are_denied(
    api_factory: async_sessionmaker[AsyncSession],
) -> None:
    journal, directory = await prepare(api_factory)
    action = await pending(journal, decision=False)
    await directory.set_work_active(control(), task_id=TASK, active=False)
    app = create_company_app(CompanyServices(directory, journal, CompanyControls(api_factory)))
    async with AsyncTestClient(app) as client:
        for path in (BASE, f"{BASE}/actions/{action.action_id}"):
            owner = await client.get(path, params={"trace_id": str(TRACE)}, headers=headers(OWNER))
            assert owner.status_code == 200
            actor = await client.get(path, params={"trace_id": str(TRACE)}, headers=headers())
            assert actor.status_code == 403
        denied = await client.post(
            f"{BASE}/actions/{action.action_id}/decision",
            json={"trace_id": str(TRACE), "expected_hash": action_hash(action), "approved": True},
            headers=headers(OWNER),
        )
        assert denied.status_code == 403
