"""Actual same-source session/Unix endpoint witnesses; no credentials or cached permission."""

from importlib import import_module
from pathlib import Path

from pydantic import AwareDatetime, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from nexus.company.management.base import Name, ValueContract
from nexus.operations.backup_config import LocalPostgresBackupConfig

PINNED_ASYNCPG_VERSION = "0.31.0"


class DatabaseBinding(ValueContract):
    """Server-observed connection metadata, never caller permission or remote attestation."""

    database: Name
    port: int = Field(ge=1, le=65535)
    server_address: str | None
    backend_pid: int = Field(gt=0)
    backend_start: AwareDatetime
    socket_peer: Name


async def unix_peer(reader: AsyncConnection | AsyncSession) -> str:
    """Isolate the pinned driver's private transport; unsupported access fails closed."""
    try:
        connection = await reader.connection() if isinstance(reader, AsyncSession) else reader
        raw = await connection.get_raw_connection()
        driver = raw.driver_connection
        # asyncpg 0.31 lacks typing stubs; validate its actual pinned class and transport here.
        module = import_module("asyncpg")
        driver_class = getattr(module, "Connection", None)
        if (
            getattr(module, "__version__", None) != PINNED_ASYNCPG_VERSION
            or not isinstance(driver_class, type)
            or not isinstance(driver, driver_class)
        ):
            raise ValueError("Backup source session binding is unavailable")
        transport = getattr(driver, "_transport", None)
        accessor = getattr(transport, "get_extra_info", None)
        if not callable(accessor):
            raise ValueError("Backup source session binding is unavailable")
        peer = accessor("peername")
        if not isinstance(peer, str) or not Path(peer).is_absolute():
            raise ValueError("Backup source session binding is unavailable")
        return peer
    except (
        AttributeError,
        ImportError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        SQLAlchemyError,
    ):
        raise ValueError("Backup source session binding is unavailable") from None


async def database_binding(reader: AsyncConnection | AsyncSession) -> DatabaseBinding:
    """Observe actual SQL/backend metadata and the actual connected Unix transport."""
    try:
        result = await reader.execute(
            text(
                "SELECT current_database() AS database,current_setting('port')::int AS port,"
                "inet_server_addr()::text AS server_address,pg_backend_pid() AS backend_pid,"
                "backend_start FROM pg_stat_activity WHERE pid=pg_backend_pid()"
            )
        )
        values = dict(result.mappings().one())
        return DatabaseBinding.model_validate(values | {"socket_peer": await unix_peer(reader)})
    except (SQLAlchemyError, ValueError):
        raise ValueError("Backup source session binding is unavailable") from None


async def require_owner_source_binding(
    owner_session: AsyncSession, source: AsyncConnection, config: LocalPostgresBackupConfig
) -> None:
    """Compare this owner session to the actual configured admin source and live backend."""
    admin, owner = await database_binding(source), await database_binding(owner_session)
    expected_peer = str(config.socket / f".s.PGSQL.{config.port}")
    if any(
        row.database != config.source_database
        or row.port != config.port
        or row.server_address is not None
        or row.socket_peer != expected_peer
        for row in (admin, owner)
    ):
        raise ValueError("Backup owner session differs from the configured source")
    try:
        directories = await source.scalar(text("SELECT current_setting('unix_socket_directories')"))
        if directories != str(config.socket):
            raise ValueError("Backup source socket configuration is unavailable")
        record = (
            (
                await source.execute(
                    text(
                        "SELECT datname,backend_start,client_addr::text AS client_address "
                        "FROM pg_stat_activity WHERE pid=:pid"
                    ),
                    {"pid": owner.backend_pid},
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            record is None
            or record["datname"] != owner.database
            or record["backend_start"] != owner.backend_start
            or record["client_address"] is not None
        ):
            raise ValueError("Backup owner backend differs from the configured source")
    except (SQLAlchemyError, ValueError):
        raise ValueError("Backup source session binding is unavailable") from None
