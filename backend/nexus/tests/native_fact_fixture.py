"""Exclusive normal015 actual plan/report facts; no provider, dispatch or synthetic pass row."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.management.scheduling_contracts import SchedulerPolicy
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import migrate
from nexus.tests.native_profile_support import ProfileScenario, configured_profile


@pytest.fixture
async def facts_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_native_events"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
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
                # Only this disposable assigned fixture DB: normal015 intentionally refuses
                # downgrade while native kinds survive. Preserve that production safeguard.
                await connection.execute(text("TRUNCATE company_brain_events CASCADE"))
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


async def configured_facts(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> tuple[NativeFactServices, ProfileScenario]:
    case = await configured_profile(factory, root)
    native = case.native
    catalog, artifacts, freshness = (
        native.publisher.catalog,
        native.artifacts,
        native.publisher.freshness,
    )
    scheduler = SchedulerServices(
        SchedulerPolicy(recipe_version="native-facts-v1", workflows=(native.registration,)),
        catalog,
        artifacts,
        freshness,
        native.identities,
        native.resources,
    )
    return NativeFactServices(
        catalog,
        artifacts,
        freshness,
        scheduler,
        native.publisher.rules["company.report.write.v1"].target,
    ), case
