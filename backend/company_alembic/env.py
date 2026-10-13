"""Independent company migration environment, with no legacy worker/schema startup."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from nexus.company.brain.models import BrainBase
from nexus.company.directory_models import DirectoryBase
from nexus.execution.billing_models import BillingEvidenceBase
from nexus.execution.dispatch_models import DispatchBase
from nexus.execution.runtime_models import ExecutionBase
from nexus.harness.authorization_models import AuthorityBase
from nexus.harness.journal_models import JournalBase
from nexus.harness.standing_models import StandingBase
from nexus.settings import settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = [
    JournalBase.metadata,
    DirectoryBase.metadata,
    ExecutionBase.metadata,
    StandingBase.metadata,
    AuthorityBase.metadata,
    DispatchBase.metadata,
    BillingEvidenceBase.metadata,
    BrainBase.metadata,
]


def include_object(
    object_: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Ignore unrelated legacy objects; Any is Alembic's generic reflection callback."""
    if type_ == "table":
        return bool(name and name.startswith("company_") and name != "company_alembic_version")
    return True


def database_url() -> str:
    """Use explicit config/Settings only, failing closed when no profile URL is set."""
    url = config.get_main_option("sqlalchemy.url") or settings.company_database_url
    if not url:
        raise RuntimeError("COMPANY_DATABASE_URL must explicitly select the company database")
    return url


def do_run_migrations(connection: Connection) -> None:
    """Apply only the independent company lineage with its own version history."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table="company_alembic_version",
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create a private migration engine and dispose it after the command."""
    engine = create_async_engine(database_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table="company_alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied = config.attributes.get("connection")
    if supplied is not None:
        do_run_migrations(supplied)
    else:
        asyncio.run(run_async_migrations())
