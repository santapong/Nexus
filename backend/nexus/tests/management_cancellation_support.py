"""Dedicated normal company011 restricted database; no operative rows or verdicts are invented."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.settings import settings
from nexus.tests.integration.test_company_directory import migrate


@pytest.fixture
async def cancellation_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Own only the explicitly assigned cancellation database, upgrading/downgrading normally."""
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_cancellation"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
    migrated = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
            # This owned private DB proves DELETE reaches the immutable trigger,
            # rather than mistaking the role's default lack of DELETE for immutability.
            await connection.execute(
                text("GRANT DELETE ON company_management_cancellations TO nexus_company_app")
            )
        migrated = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if migrated:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


@pytest.fixture
async def old_cancellation_factory(
    request: pytest.FixtureRequest,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Normal pre011 installations stay readable/recoverable without probing a missing table."""
    from alembic import command
    from nexus.tests.integration.test_company_profile_migrations import profile_config

    revision = request.param
    assert type(revision) is str and revision in {"company_007", "company_010"}
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_cancellation"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
    try:
        async with admin.begin() as connection:
            await connection.run_sync(
                lambda native: command.upgrade(profile_config(native), revision)
            )
            await connection.execute(
                text(
                    "GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public "
                    "TO nexus_company_app"
                )
            )
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await admin.dispose()
