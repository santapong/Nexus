"""Exclusive normal013 schema checks with a restricted application role."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.settings import settings
from nexus.tests.integration.test_company_directory import migrate


@pytest.fixture
async def metric_schema_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Install/teardown only the assigned DB; DELETE must reach the immutable trigger."""
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_metric_schema"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    installed = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
            await connection.execute(
                text("GRANT DELETE ON company_management_metric_observations TO nexus_company_app")
            )
        installed = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if installed:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()
