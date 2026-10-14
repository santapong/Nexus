"""Exclusive actual metric HTTP/native-store composition with a restricted role."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from litestar import Litestar
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.company.control_store import CompanyControls
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.api_services import ManagementApiServices
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.metric_queries import MetricQueries
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.owner_view_store import ManagementOwnerViews
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.services import CompanyServices
from nexus.company_app import create_company_app
from nexus.harness.journal import CompanyJournal
from nexus.settings import settings
from nexus.tests.integration.test_company_api import KEY
from nexus.tests.integration.test_company_directory import migrate
from nexus.tests.metric_fixture import MetricScenario, configured_metric


@pytest.fixture
async def metric_api_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    monkeypatch.setattr(settings, "jwt_secret_key", KEY)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_metrics_api"
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


async def configured_metric_api(
    factory: async_sessionmaker[AsyncSession], root: Path, *, enabled: bool = True
) -> tuple[Litestar, MetricScenario]:
    case = await configured_metric(factory, root)
    directory = PersistentCompanyDirectory(factory)
    management = ManagementApiServices(
        directory,
        ManagementControlStore(factory),
        GoalStore(factory, case.retriever),
        ManagementPlanStore(factory, case.store.catalog, source_freshness=case.store.freshness),
        metrics=case.store if enabled else None,
        views=ManagementOwnerViews(
            factory, OwnerViewSources(case.store.artifacts, case.store.freshness)
        ),
        metric_queries=MetricQueries(
            factory, case.store.catalog, case.store.artifacts, case.store.freshness
        )
        if enabled
        else None,
    )
    app = create_company_app(
        CompanyServices(directory, CompanyJournal(factory), CompanyControls(factory)),
        management_services=management,
    )
    return app, case
