"""Normal rollback refuses persisted native wakes before removing their selector columns."""

from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Connection, Table, func, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from nexus.company.brain.event_models import BrainEvent
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import COMPANY
from nexus.tests.integration.test_company_native_event_schema import (
    native_schema_factory as native_schema_factory,
)
from nexus.tests.integration.test_company_native_event_schema import schema_event_values
from nexus.tests.integration.test_company_profile_migrations import profile_config
from nexus.tests.native_profile_support import configured_profile


def downgrade014(connection: Connection) -> None:
    """Actual normal Alembic downgrade, under a test savepoint only."""
    command.downgrade(profile_config(connection), "company_014")


async def test_native_event_downgrade_failure_preserves_version_row_and_columns(
    native_schema_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await configured_profile(native_schema_factory, tmp_path)
    async with native_schema_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        values, _ = await schema_event_values(session, case)
    admin = create_async_engine(settings.company_test_database_url)
    try:
        async with admin.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(insert(cast(Table, BrainEvent.__table__)).values(**values))
                with pytest.raises(DBAPIError, match="ck_brain_event_kind"):
                    async with connection.begin_nested():
                        await connection.run_sync(downgrade014)
                assert (
                    await connection.scalar(text("SELECT version_num FROM company_alembic_version"))
                    == "company_015"
                )
                assert (
                    await connection.scalar(
                        text(
                            "SELECT native_snapshot_sha256 FROM company_brain_events "
                            "WHERE event_id=:event"
                        ),
                        {"event": values["event_id"]},
                    )
                    == "a" * 64
                )
            finally:
                await transaction.rollback()
    finally:
        await admin.dispose()
