"""Exclusive native generated-artifact DB through normal company012 and restricted app role."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.settings import settings
from nexus.tests.integration.test_company_directory import migrate


@pytest.fixture
async def generated_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Normal migrations only, never a fake native publication or schema stamp."""
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_generated_artifacts"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
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
