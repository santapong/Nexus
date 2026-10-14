"""Exclusive old-profile event compatibility fixture; no015 install before Root handshake."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Connection, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from nexus.settings import settings


def migrate_event_profile(connection: Connection, target: str) -> None:
    """Run explicit normal revision/base commands, with no metadata/stamp shortcut."""
    backend = Path(__file__).resolve().parents[2]
    config = Config(str(backend / "alembic_company.ini"))
    config.set_main_option("script_location", str(backend / "company_alembic"))
    config.attributes["connection"] = connection
    if target == "base":
        command.downgrade(config, target)
    else:
        command.upgrade(config, target)
        connection.execute(
            text("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO nexus_company_app")
        )
        connection.execute(
            text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nexus_company_app")
        )


@pytest.fixture(params=["company_008", "company_014"])
async def old_event_factory(
    request: pytest.FixtureRequest,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_native_events"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
    installed = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate_event_profile, str(request.param))
        installed = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if installed:
            async with admin.begin() as connection:
                await connection.run_sync(migrate_event_profile, "base")
        await admin.dispose()
