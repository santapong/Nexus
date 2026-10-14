"""Fixed owner notification worker reconstructs current authority inside a nonretry step."""

import asyncio
from pathlib import Path

import httpx
from dbos import DBOS, _dbos
from dbos._serialization import WorkflowSerializationFormat
from pydantic import AwareDatetime, Field, StrictBool
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.company.management.base import ValueContract
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.notification_worker_context import prepare_notification_context
from nexus.execution.notification_worker_contracts import NotificationSegmentResult
from nexus.execution.notification_worker_effect import run_notification_effect
from nexus.execution.notification_worker_observation import observe_notification_segment
from nexus.execution.notification_worker_services import (
    NOTIFICATION_APPLICATION,
    NOTIFICATION_QUEUE,
    NOTIFICATION_VERSION,
    NOTIFICATION_WORKFLOW,
    NotificationDispatchWorkerServices,
)

_services: NotificationDispatchWorkerServices | None = None
_system_engine: Engine | None = None
_DATABASE_WITNESS_SQL = (
    "SELECT current_database() AS database,current_user AS username,"
    "current_setting('port')::int AS port,inet_server_addr()::text AS server_address,"
    "pg_backend_pid() AS backend_pid,backend_start,client_addr::text AS client_address,"
    "(SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user) AS elevated "
    "FROM pg_stat_activity WHERE pid=pg_backend_pid()"
)


class NotificationDatabaseWitness(ValueContract):
    """Internal observed connection metadata; this descriptive value confers no authority."""

    database: str
    username: str
    port: int = Field(strict=True, ge=1, le=65535)
    server_address: str | None
    backend_pid: int = Field(strict=True, gt=0)
    backend_start: AwareDatetime
    client_address: str | None
    elevated: StrictBool


def _database_endpoint(url: URL) -> tuple[str, int, str, str]:
    """Only an explicit one-host/socket configuration can be compared without guessing aliases."""
    if url.get_backend_name() != "postgresql" or set(url.query) - {"host", "port", "sslmode"}:
        raise ValueError("Notification database endpoint is unavailable")
    host = url.query.get("host", url.host)
    port = url.query.get("port", str(url.port if url.port is not None else 5432))
    if (
        not isinstance(host, str)
        or not host
        or any(c.isspace() or c == "," for c in host)
        or ("host" in url.query and url.host is not None)
        or ("port" in url.query and url.port is not None)
        or not isinstance(port, str)
        or not port.isascii()
        or not port.isdecimal()
        or not 1 <= int(port) <= 65535
        or not url.database
        or not url.username
        or (host.startswith("/") and ".." in Path(host).parts)
    ):
        raise ValueError("Notification database endpoint is unavailable")
    return host, int(port), url.database, url.username


def require_database_endpoint(services: NotificationDispatchWorkerServices, system: URL) -> None:
    """Compare business Engine configuration; actual live-backend proof follows at launch."""
    bind = services.reads.factory.kw.get("bind")
    if not isinstance(bind, AsyncEngine) or _database_endpoint(bind.url) != _database_endpoint(
        system
    ):
        raise ValueError("Notification database endpoint is unavailable")


def configure_notification_worker(
    services: NotificationDispatchWorkerServices, system_database_url: str
) -> None:
    """Trusted composition pins the application; a failed constructor cannot poison services."""
    global _services, _system_engine
    if (
        _services is not None
        or _system_engine is not None
        or _dbos._dbos_global_instance is not None
    ):
        raise ValueError("Notification worker is already configured")
    services.require_enabled()
    url = make_url(system_database_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("Notification system database must use PostgreSQL")
    url = url.set(drivername="postgresql+psycopg")
    require_database_endpoint(services, url)
    engine = create_engine(url, pool_size=4, max_overflow=0, pool_timeout=30)
    try:
        DBOS(
            config={
                "name": NOTIFICATION_APPLICATION,
                "application_version": NOTIFICATION_VERSION,
                "system_database_url": url.render_as_string(hide_password=False),
                "system_database_engine": engine,
                "run_migrations": False,
                "executor_id": services.executor_id,
                "enable_otlp": False,
                "use_listen_notify": False,
                "log_level": "WARNING",
                "sys_db_pool_size": 4,
                "max_executor_threads": 4,
            }
        )
    except BaseException:
        engine.dispose()
        raise
    _services = services
    _system_engine = engine


def require_system_role(engine: Engine, business: NotificationDatabaseWitness) -> None:
    """Inspect the exact SDK engine and its view of the still-open business backend."""
    with engine.connect() as connection:
        actual = connection.execute(text(_DATABASE_WITNESS_SQL)).mappings().one()
        system = NotificationDatabaseWitness.model_validate(dict(actual))
        peer = (
            connection.execute(
                text(
                    "SELECT datname AS database,usename AS username,backend_start,"
                    "client_addr::text AS client_address FROM pg_stat_activity WHERE pid=:pid"
                ),
                {"pid": business.backend_pid},
            )
            .mappings()
            .one_or_none()
        )
    if (
        business.elevated
        or system.elevated
        or (system.database, system.username, system.port, system.server_address)
        != (business.database, business.username, business.port, business.server_address)
        or peer is None
        or dict(peer)
        != business.model_dump(include={"database", "username", "backend_start", "client_address"})
    ):
        raise ValueError("Notification system role or database is unavailable")


async def launch_notification_worker() -> None:
    """Register the bounded fixed queue only from the explicitly enabled trusted service."""
    if _services is None or _system_engine is None:
        raise ValueError("Notification worker services unavailable")
    _services.require_enabled()
    require_database_endpoint(_services, _system_engine.url)
    async with _services.reads.factory() as session:
        observed = (await session.execute(text(_DATABASE_WITNESS_SQL))).mappings().one()
        business = NotificationDatabaseWitness.model_validate(dict(observed))
        if business.elevated:
            raise ValueError("Notification runtime cannot bypass company RLS")
        await asyncio.to_thread(require_system_role, _system_engine, business)
    DBOS.launch()
    await DBOS.register_queue_async(
        NOTIFICATION_QUEUE,
        global_concurrency=1,
        worker_concurrency=1,
        polling_interval_sec=1.0,
    )


@DBOS.workflow(name=NOTIFICATION_WORKFLOW, serialization_type=WorkflowSerializationFormat.PORTABLE)
async def notification_segment(payload: str) -> str:
    """Portable payload carries only the exact immutable native command."""
    return await notification_effect_step(payload)


@DBOS.step(name="nexus.notification.effect.v1", retries_allowed=False)
async def notification_effect_step(payload: str) -> str:
    """Native intent, current windows and no-reissue reconciliation stay within one step."""
    if _services is None or DBOS.workflow_id is None:
        raise ValueError("Notification durable step services unavailable")
    command = SegmentCommand.model_validate_json(payload)
    result = await execute_notification_segment(_services, command, workflow_id=DBOS.workflow_id)
    return result.model_dump_json()


async def execute_notification_segment(
    services: NotificationDispatchWorkerServices, command: SegmentCommand, *, workflow_id: str
) -> NotificationSegmentResult:
    """Describe actual history before release; exceptions cannot downgrade a known receipt."""
    context = await prepare_notification_context(services, command, workflow_id=workflow_id)
    failure: str | None = None
    try:
        try:
            await run_notification_effect(services, context)
        except (ValueError, TimeoutError, httpx.HTTPError) as exc:
            failure = type(exc).__name__
        return await observe_notification_segment(services, context, failure_kind=failure)
    finally:
        await services.execution.release(context.lease, context.identity)
