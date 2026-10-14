"""Fixed local PostgreSQL17.6 custom dump/empty-target restore; never create, drop or reset."""

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic

from pydantic import Field
from sqlalchemy import URL, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.company.management.base import ValueContract
from nexus.operations.backup_auth_file import empty_password_file
from nexus.operations.backup_binding import require_owner_source_binding
from nexus.operations.backup_config import PG_BIN, LocalPostgresBackupConfig
from nexus.operations.backup_process import run_bounded


class PostgresRestoreReceipt(ValueContract):
    database: str
    elapsed_seconds: float = Field(ge=0)


class PostgresBackupAdapter:
    def __init__(self, config: LocalPostgresBackupConfig) -> None:
        self.config = config
        self._operation = asyncio.Lock()

    async def require_owner_binding(self, session: AsyncSession) -> None:
        """Bind this actual owner transaction to the configured current source endpoint."""
        async with self.connection() as source:
            await require_source(source, self.config)
            await require_owner_source_binding(session, source, self.config)

    @asynccontextmanager
    async def connection(self, *, target: bool = False) -> AsyncIterator[AsyncConnection]:
        with empty_password_file() as passfile:
            async with self._connection(target, str(passfile)) as connection:
                yield connection

    @asynccontextmanager
    async def _connection(self, target: bool, passfile: str) -> AsyncIterator[AsyncConnection]:
        self.config.require_enabled()
        if self.config.socket.resolve() != self.config.socket or not self.config.socket.is_dir():
            raise ValueError("Backup local socket is unavailable")
        engine = create_async_engine(
            URL.create(
                "postgresql+asyncpg",
                username=self.config.admin_user,
                database=self.config.target_database if target else self.config.source_database,
                query={"host": str(self.config.socket), "port": str(self.config.port)},
            ),
            poolclass=NullPool,
            hide_parameters=True,
            connect_args={
                "passfile": passfile,
                "timeout": 5,
                "server_settings": {
                    "application_name": "nexus-backup-operator",
                    "statement_timeout": "30000",
                },
            },
        )
        try:
            async with engine.connect() as connection:
                yield connection
        except (OSError, SQLAlchemyError, TimeoutError):
            raise ValueError("Backup local database is unavailable") from None
        finally:
            await engine.dispose()

    async def clients(self) -> None:
        for name in ("pg_dump", "pg_restore"):
            raw = await run_bounded(
                (str(PG_BIN / name), "--version"), output_limit=1024, timeout_seconds=5
            )
            if not raw.startswith(f"{name} (PostgreSQL) 17.6 ".encode()):
                raise ValueError("Backup PostgreSQL client version is unavailable")

    def arguments(self, *, target: bool = False) -> tuple[str, ...]:
        return (
            f"--host={self.config.socket}",
            f"--port={self.config.port}",
            f"--username={self.config.admin_user}",
            "--no-password",
            f"--dbname={self.config.target_database if target else self.config.source_database}",
        )

    async def dump(self, snapshot_id: str | None = None) -> bytes:
        self.config.require_enabled()
        if snapshot_id is not None and not re.fullmatch(r"[0-9A-Fa-f-]{1,80}", snapshot_id):
            raise ValueError("Backup snapshot is unavailable")
        async with self._operation:
            await self.clients()
            async with self.connection() as connection:
                await require_source(connection, self.config)
            extra = (f"--snapshot={snapshot_id}",) if snapshot_id else ()
            raw = await run_bounded(
                (str(PG_BIN / "pg_dump"), *self.arguments(), "--format=custom", *extra),
                output_limit=self.config.max_bytes,
                timeout_seconds=self.config.timeout_seconds,
            )
            require_custom_dump(raw, self.config.max_bytes)
            return raw

    async def restore(self, database: bytes) -> PostgresRestoreReceipt:
        self.config.require_enabled()
        require_custom_dump(database, self.config.max_bytes)
        async with self._operation:
            await self.clients()
            async with self.connection(target=True) as connection:
                await require_empty_target(connection)
            started = monotonic()
            await run_bounded(
                (
                    str(PG_BIN / "pg_restore"),
                    *self.arguments(target=True),
                    "--single-transaction",
                    "--exit-on-error",
                ),
                input_bytes=database,
                output_limit=65536,
                timeout_seconds=self.config.timeout_seconds,
            )
            async with self.connection(target=True) as connection:
                await require_source(connection, self.config)
            return PostgresRestoreReceipt(
                database=self.config.target_database, elapsed_seconds=monotonic() - started
            )


def require_custom_dump(raw: bytes, limit: int) -> None:
    if type(raw) is not bytes or not 5 <= len(raw) <= limit or not raw.startswith(b"PGDMP"):
        raise ValueError("Backup custom archive is unavailable")


async def require_source(connection: AsyncConnection, config: LocalPostgresBackupConfig) -> None:
    version = await connection.scalar(text("SELECT version_num FROM company_alembic_version"))
    companies = tuple(
        (
            await connection.scalars(
                text("SELECT company_id FROM company_directory ORDER BY company_id")
            )
        ).all()
    )
    if version != config.company_revision or companies != (config.company_id,):
        raise ValueError("Backup native company/profile differs")
    if not await connection.scalar(text("SELECT to_regclass('dbos.workflow_status') IS NOT NULL")):
        raise ValueError("Backup full DBOS schema is unavailable")


async def require_empty_target(connection: AsyncConnection) -> None:
    count = await connection.scalar(
        text(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname NOT IN ('pg_catalog','information_schema') "
            "AND n.nspname NOT LIKE 'pg_toast%'"
        )
    )
    if count:
        raise ValueError("Backup restore target is not empty")
