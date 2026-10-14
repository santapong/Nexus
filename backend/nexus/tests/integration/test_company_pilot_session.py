"""Real operator bootstrap/password/JWT/company HTTP flow in exclusive disposable owner UAT DB."""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from litestar import Litestar
from litestar.testing import AsyncTestClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.api.company_auth import require_company_identity
from nexus.company.access import CompanyControlScope
from nexus.company.control_store import CompanyControls
from nexus.company.directory_contracts import CompanyRegistration, MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.pilot_session import PilotSessionService
from nexus.company.pilot_session_store import PilotCredential, PilotCredentialFile, save_credentials
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import CompanyPolicy, LedgerScope
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import migrate


@pytest.fixture
async def uat_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_owner_uat"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool),
    )
    migrated = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        migrated = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if migrated:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


async def configured_session(
    factory: async_sessionmaker[AsyncSession], root: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Litestar, PersistentCompanyDirectory, CompanyControlScope, str]:
    monkeypatch.setattr(settings, "jwt_secret_key", "ephemeral-unit-signer-" + "x" * 48)
    company, owner, workspace = uuid4(), uuid4(), uuid4()
    scope = CompanyControlScope(
        company_id=company, principal_id=owner, operation_id=uuid4(), trace_id=uuid4()
    )
    directory, journal = PersistentCompanyDirectory(factory), CompanyJournal(factory)
    await journal.create_company(
        CompanyPolicy(
            company_id=company,
            owner_id=owner,
            policy_version="uat-only-v1",
            price_version="uat-offline-v1",
        ),
        LedgerScope(
            company_id=company,
            principal_id=owner,
            task_id=scope.operation_id,
            trace_id=scope.trace_id,
        ),
    )
    await directory.bootstrap(
        CompanyRegistration(company_id=company, workspace_id=workspace, owner_id=owner), scope
    )
    path = root / "private" / "accounts.json"
    invite = "synthetic-test-invitation-" + "s" * 48
    save_credentials(
        path,
        PilotCredentialFile(
            accounts=(
                PilotCredential(
                    company_id=company,
                    principal_id=owner,
                    workspace_id=workspace,
                    email="owner-test@example.invalid",
                    display_name="Disposable UAT owner",
                    signup_sha256=hashlib.sha256(invite.encode()).hexdigest(),
                    signup_expires_at=datetime.now(UTC) + timedelta(minutes=10),
                ),
            )
        ),
    )
    sessions = PilotSessionService(directory, path)
    app = create_company_app(
        CompanyServices(directory, journal, CompanyControls(factory)), pilot_sessions=sessions
    )
    return app, directory, scope, invite


async def test_actual_signup_login_issuer_current_owner_read_and_revoke(
    uat_factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, directory, scope, invite = await configured_session(uat_factory, tmp_path, monkeypatch)
    async with AsyncTestClient(app=app, raise_server_exceptions=True) as client:
        payload = {
            "email": "owner-test@example.invalid",
            "password": "synthetic-passphrase-value",
            "invitation": invite,
        }
        signed = await client.post("/api/v2/company-session/signup", json=payload)
        assert signed.status_code == 201
        token = signed.json()["access_token"]

        class Auth:
            def __init__(self) -> None:
                self.headers = {"authorization": "Bearer " + token}

        actual = require_company_identity(Auth())
        assert actual.principal_id == scope.principal_id
        headers = {"Authorization": "Bearer " + token}
        assert (await client.get("/api/v2/company", headers=headers)).status_code == 200
        login = await client.post(
            "/api/v2/company-session/login",
            json={key: value for key, value in payload.items() if key != "invitation"},
        )
        assert login.status_code == 200
        invalid = await client.post(
            "/api/v2/company-session/login",
            json={"email": payload["email"], "password": "incorrect-long-password"},
        )
        assert invalid.status_code == 401
        await directory.set_membership(
            MembershipChange(
                company_id=scope.company_id,
                principal_id=scope.principal_id,
                role="owner",
                membership_active=False,
            ),
            scope,
        )
        assert (await client.get("/api/v2/company", headers=headers)).status_code == 403
        assert (
            await client.post(
                "/api/v2/company-session/login",
                json={key: value for key, value in payload.items() if key != "invitation"},
            )
        ).status_code == 401


async def test_only_one_concurrent_invitation_signup_can_win(
    uat_factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _, _, invite = await configured_session(uat_factory, tmp_path, monkeypatch)
    async with AsyncTestClient(app=app, raise_server_exceptions=True) as client:
        payload = {
            "email": "owner-test@example.invalid",
            "password": "synthetic-passphrase-value",
            "invitation": invite,
        }
        results = await asyncio.gather(
            *(client.post("/api/v2/company-session/signup", json=payload) for _ in range(2))
        )
        assert sorted(row.status_code for row in results) == [201, 401]
