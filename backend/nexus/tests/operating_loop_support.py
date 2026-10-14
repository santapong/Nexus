"""Exclusive normal013 native loop fixture and actual owner exact decision helper."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from dbos import DBOS
from litestar.testing import AsyncTestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.company.control_store import CompanyControls
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.native_loop_contracts import NativeOperatingRegistration
from nexus.company.management.native_loop_store import NativeReportOperatingLoop
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import ActionRecord
from nexus.settings import settings
from nexus.tests.generated_artifact_fixture import ledger
from nexus.tests.integration.test_company_api import KEY, headers
from nexus.tests.integration.test_company_directory import OWNER, control, migrate
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.native_profile_support import ProfileScenario, configured_profile


@pytest.fixture
async def loop_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    monkeypatch.setattr(settings, "jwt_secret_key", KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_operating_loop"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool),
    )
    installed = False
    try:
        await asyncio.to_thread(
            DBOS.migrate,
            url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
            application_role="nexus_company_app",
        )
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        installed = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        async with admin.begin() as connection:
            if installed:
                await connection.run_sync(migrate, "downgrade")
            await connection.execute(text("DROP SCHEMA IF EXISTS dbos CASCADE"))
        await admin.dispose()


async def configured_loop(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> tuple[NativeReportOperatingLoop, ProfileScenario]:
    """One public owner-approved plan/report/current due commitment, never a raw pass row."""
    case = await configured_profile(factory, root)
    profile = await case.preparation.resolve_profile(
        control(), identity(OWNER), case.report_id, case.commitment_id, case.evidence_ids
    )
    registration = NativeOperatingRegistration(
        company_id=profile.company_id, registration_id=uuid4(), profile=profile.reference
    )
    return NativeReportOperatingLoop(registration, case.preparation, case.native), case


async def decide_and_authorize(
    factory: async_sessionmaker[AsyncSession], case: ProfileScenario, pending: ActionRecord
) -> None:
    """A separate actual signed owner operation grants exact action authority, not tick."""
    action = pending.proposal
    binding = next(
        row.binding for row in case.payload.children if row.binding.task_id == action.task_id
    )
    journal = CompanyJournal(factory)
    await journal.approve_registered(
        ledger(binding).model_copy(update={"principal_id": OWNER}),
        action.action_id,
        action_hash(action),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        ledger(binding),
        action.action_id,
        datetime.now(UTC),
        (),
        identity=identity(binding.actor_id),
    )


async def decide_existing(factory: async_sessionmaker[AsyncSession], pending: ActionRecord) -> None:
    """Actual signed owner HTTP decision records approval only; tick must consume it itself."""
    action = pending.proposal
    services = CompanyServices(
        PersistentCompanyDirectory(factory), CompanyJournal(factory), CompanyControls(factory)
    )
    async with AsyncTestClient(create_company_app(services)) as client:
        response = await client.post(
            f"/api/v2/companies/{action.company_id}/work/{action.task_id}/actions/{action.action_id}/decision",
            headers=headers(OWNER),
            json={
                "trace_id": str(action.trace_id),
                "expected_hash": action_hash(action),
                "approved": True,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["scheduled"] is False
        record = ActionRecord.model_validate_json(json.dumps(response.json()["record"]))
        assert (
            record.consumed_at is None
            and record.approval
            and record.approval.decision == "approved"
        )
