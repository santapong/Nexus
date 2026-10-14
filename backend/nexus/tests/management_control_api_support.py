"""Exclusive control HTTP database; normal012, restricted runtime and actual public plan setup."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from litestar import Litestar
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.api.company_management_control_routes import CompanyManagementControlController
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.control_store import CompanyControls
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.cancellation_store import WorkCancellationStore
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import PlanPayload
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.harness.journal import CompanyJournal
from nexus.settings import settings
from nexus.tests.integration.test_company_api import KEY
from nexus.tests.integration.test_company_directory import OWNER, control, migrate
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_plan_support import configured_plan


@pytest.fixture
async def control_api_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    monkeypatch.setattr(settings, "jwt_secret_key", KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_control_api"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool)
    installed = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        installed = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if installed:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


@dataclass(frozen=True)
class ControlApiScenario:
    app: Litestar
    plans: ManagementPlanStore
    payload: PlanPayload
    directory: PersistentCompanyDirectory
    cancellations: WorkCancellationStore


async def configured_control_api(
    factory: async_sessionmaker[AsyncSession], root: Path, *, enabled: bool = True
) -> ControlApiScenario:
    plans, payload = await configured_plan(factory, root)
    proposed = await plans.propose(
        control(), identity(OWNER), payload, expected_current_revision_id=None
    )
    await plans.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=proposed.plan_revision_id,
    )
    directory = PersistentCompanyDirectory(factory)
    cancellations = WorkCancellationStore(factory)
    retriever = PersistentBrainRetriever(
        factory,
        ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"),
        limits=RetrievalLimits(),
    )
    management = ManagementApiServices(
        directory,
        ManagementControlStore(factory),
        GoalStore(factory, retriever),
        plans,
        cancellations=cancellations if enabled else None,
    )
    app = create_company_app(
        CompanyServices(directory, CompanyJournal(factory), CompanyControls(factory)),
        management_services=management,
    )
    # Root owns production mounting; this explicit isolated test mount exercises
    # the actual router now without changing the shared app factory.
    if not any(route.path.rstrip("/").endswith("/management/control") for route in app.routes):
        app.register(CompanyManagementControlController)
    return ControlApiScenario(app, plans, payload, directory, cancellations)
