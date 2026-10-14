"""Exclusive new disposable normal-profile immediate-acquisition negative fixture."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.settings import settings
from nexus.tests.integration.test_company_directory import migrate


@pytest.fixture
async def immediate_negative_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_engineering_immediate_negative"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await admin.dispose()
