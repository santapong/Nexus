"""Exclusive signed-owner report/profile HTTP composition; no worker is launched."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from litestar import Litestar
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.control_store import CompanyControls
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.harness.journal import CompanyJournal
from nexus.settings import settings
from nexus.tests.integration.test_company_api import KEY
from nexus.tests.integration.test_company_directory import migrate
from nexus.tests.native_profile_support import ProfileScenario, configured_profile


@pytest.fixture
async def report_api_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    monkeypatch.setattr(settings, "jwt_secret_key", KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_native_report_api"
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


async def configured_report_api(
    factory: async_sessionmaker[AsyncSession], root: Path, *, enabled: bool = True
) -> tuple[Litestar, ProfileScenario]:
    case = await configured_profile(factory, root)
    directory = PersistentCompanyDirectory(factory)
    reader = PersistentBrainRetriever(
        factory,
        ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"),
        limits=RetrievalLimits(),
    )
    management = ManagementApiServices(
        directory,
        ManagementControlStore(factory),
        GoalStore(factory, reader),
        ManagementPlanStore(
            factory, case.preparation.catalog, source_freshness=case.preparation.freshness
        ),
        reports=case.native.producer.reports if enabled else None,
        report_preparation=case.preparation if enabled else None,
    )
    return create_company_app(
        CompanyServices(directory, CompanyJournal(factory), CompanyControls(factory)),
        management_services=management,
    ), case
