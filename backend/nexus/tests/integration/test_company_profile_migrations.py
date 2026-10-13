"""Independent company install proof; unrelated legacy data must remain unchanged."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, MetaData, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from nexus.company.directory_models import DirectoryBase
from nexus.execution.billing_models import BillingEvidenceBase
from nexus.execution.dispatch_models import DispatchBase
from nexus.execution.runtime_models import ExecutionBase
from nexus.harness.authorization_models import AuthorityBase
from nexus.harness.journal_models import JournalBase
from nexus.harness.standing_models import StandingBase
from nexus.settings import settings


def profile_config(connection: Connection) -> Config:
    """Bind the actual disposable connection; never fall back to a production URL."""
    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "alembic_company.ini"))
    config.set_main_option("script_location", str(root / "company_alembic"))
    config.attributes["connection"] = connection
    return config


def verify_profile(connection: Connection) -> None:
    """Install, repeat, compare and remove only the explicit company lineage."""
    assert inspect(connection).get_table_names() == []
    connection.execute(
        text("CREATE TABLE legacy_release_marker (id integer PRIMARY KEY, value text)")
    )
    connection.execute(text("INSERT INTO legacy_release_marker VALUES (1, 'preserve')"))
    connection.execute(text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)"))
    connection.execute(text("INSERT INTO alembic_version VALUES ('legacy-sentinel')"))
    config = profile_config(connection)
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    assert (
        connection.scalar(text("SELECT version_num FROM company_alembic_version"))
        == ScriptDirectory.from_config(config).get_current_head()
    )
    context = MigrationContext.configure(
        connection,
        opts={
            "include_object": lambda obj, name, type_, reflected, compare: (
                type_ != "table"
                or bool(name and name.startswith("company_") and name != "company_alembic_version")
            )
        },
    )
    combined = MetaData()
    for metadata in (
        JournalBase.metadata,
        DirectoryBase.metadata,
        ExecutionBase.metadata,
        StandingBase.metadata,
        AuthorityBase.metadata,
        DispatchBase.metadata,
        BillingEvidenceBase.metadata,
    ):
        for table in metadata.sorted_tables:
            table.to_metadata(combined)
    assert compare_metadata(context, combined) == []
    assert connection.scalar(text("SELECT value FROM legacy_release_marker")) == "preserve"
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "legacy-sentinel"
    command.downgrade(config, "base")
    assert connection.scalar(text("SELECT value FROM legacy_release_marker")) == "preserve"
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "legacy-sentinel"
    connection.execute(text("DROP TABLE company_alembic_version"))
    connection.execute(text("DROP TABLE legacy_release_marker"))
    connection.execute(text("DROP TABLE alembic_version"))


async def test_company_profile_installs_without_replaying_or_touching_legacy_history() -> None:
    if not settings.company_test_database_url:
        pytest.skip("Explicit disposable company test database is not configured")
    url = make_url(settings.company_test_database_url)
    assert url.database and url.database.startswith("nexus_company_test_")
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(verify_profile)
    finally:
        await engine.dispose()
