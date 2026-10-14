"""TEST-only closed local DB/SDK fixture; failure preserves native state and owned evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
import pytest
from dbos import DBOS, _dbos
from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.company.management.base import ValueContract
from nexus.company.notifications.dispatch_store import NotificationTransportConfiguration
from nexus.execution import notification_worker as worker
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.notification_worker_contracts import NotificationSegmentResult
from nexus.execution.notification_worker_services import NotificationDispatchWorkerServices
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import migrate
from nexus.tests.notification_worker_enqueue_pg_fixture import (
    AtomicNotificationCase,
    AtomicNotificationDatabases,
    atomic_notification_case,
)

DurableFixtureDatabase = Literal[
    "nexus_company_test_notification_enqueue_atomic",
    "nexus_company_test_notification_durable_rejected",
    "nexus_company_test_notification_durable_unknown",
    "nexus_company_test_notification_process_intent",
    "nexus_company_test_notification_process_response",
    "nexus_company_test_notification_process_receipt",
    "nexus_company_test_notification_process_observation",
]
_DATABASE: DurableFixtureDatabase = "nexus_company_test_notification_enqueue_atomic"
_SOCKET = "/tmp/nexus-release-tests-2026-10-13/socket"


@dataclass
class DurableNotificationEnvironment:
    databases: AtomicNotificationDatabases
    complete: bool = False


class MockNotificationRequest(ValueContract):
    method: str
    path: str
    idempotency_key: str
    body_sha256: str
    response_sha256: str


@dataclass(frozen=True)
class DurableNotificationCase:
    atomic: AtomicNotificationCase
    requests: list[MockNotificationRequest]


def capture_host_executor() -> ThreadPoolExecutor:
    """Pinned CPython host observation; no missing, replaced or closed executor is guessed."""
    executor = getattr(asyncio.get_running_loop(), "_default_executor", None)
    if (
        not isinstance(executor, ThreadPoolExecutor)
        or getattr(executor, "_shutdown", True) is not False
    ):
        raise ValueError("Notification fixture host executor is unavailable")
    return executor


async def destroy_sdk_on_host_executor(executor: ThreadPoolExecutor) -> None:
    """SDK owns its adopted pool; destroy elsewhere and restore exact original host I/O."""
    if (
        not isinstance(executor, ThreadPoolExecutor)
        or getattr(executor, "_shutdown", True) is not False
    ):
        raise ValueError("Notification fixture host executor is unavailable")
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            executor, partial(DBOS.destroy, workflow_completion_timeout_sec=5)
        )
    finally:
        loop.set_default_executor(executor)


def qualified_durable_url(database: DurableFixtureDatabase = _DATABASE) -> URL:
    """Same one reviewed fixture pair, without printing credentials or opening a connection."""
    database = TypeAdapter(DurableFixtureDatabase).validate_python(database, strict=True)
    url = make_url(settings.company_test_database_url)
    assert (url.drivername, url.username, url.password, url.host, url.port, url.database) == (
        "postgresql+asyncpg",
        "santapong",
        None,
        None,
        None,
        database,
    )
    assert dict(url.query) == {"host": _SOCKET, "port": "55438"}
    return url


@asynccontextmanager
async def durable_notification_database_scope(
    database: DurableFixtureDatabase = _DATABASE,
) -> AsyncIterator[DurableNotificationEnvironment]:
    """Normal015/public DBOS installation; teardown only after exported complete success."""
    # Cohesive fixture exception: closed URL/empty-base, public schema installation,
    # restricted role and success-only cleanup establish one task-owned scope.
    database = TypeAdapter(DurableFixtureDatabase).validate_python(database, strict=True)
    if not settings.company_test_database_url:
        pytest.skip("Explicit owned durable notification DB is not configured")
    url = qualified_durable_url(database)
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool)
    env: DurableNotificationEnvironment | None = None
    try:
        async with admin.begin() as connection:
            assert await connection.scalar(text("SELECT current_database()")) == database
            assert await connection.scalar(text("SELECT current_user")) == "santapong"
            tables = tuple(
                (
                    await connection.scalars(
                        text(
                            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                            "ORDER BY tablename"
                        )
                    )
                ).all()
            )
            assert tables in ((), ("company_alembic_version",))
            if tables:
                assert (
                    await connection.scalar(text("SELECT count(*) FROM company_alembic_version"))
                    == 0
                )
            assert (
                await connection.scalar(text("SELECT to_regclass('dbos.workflow_status')")) is None
            )
        await asyncio.to_thread(
            DBOS.migrate,
            url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
            application_role="nexus_company_app",
        )
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        async with app.connect() as connection:
            assert await connection.scalar(text("SELECT current_database()")) == database
            assert await connection.scalar(text("SELECT current_user")) == "nexus_company_app"
            assert await connection.scalar(text("SELECT current_setting('port')")) == "55438"
            assert (
                await connection.scalar(
                    text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
                )
                is False
            )
        env = DurableNotificationEnvironment(
            AtomicNotificationDatabases(
                async_sessionmaker(app, expire_on_commit=False),
                async_sessionmaker(admin, expire_on_commit=False),
            )
        )
        yield env
    finally:
        await app.dispose()
        if env is not None and env.complete:
            async with admin.begin() as connection:
                await connection.execute(text("TRUNCATE company_brain_events CASCADE"))
                await connection.run_sync(migrate, "downgrade")
                await connection.execute(text("DROP SCHEMA dbos CASCADE"))
        await admin.dispose()


@pytest.fixture
async def durable_notification_environment() -> AsyncIterator[DurableNotificationEnvironment]:
    """Original default fixture keeps its exact closed database and lifecycle behavior."""
    async with durable_notification_database_scope() as environment:
        yield environment


@asynccontextmanager
async def durable_notification_case(
    root: Path,
    outcome: str,
    *,
    database: DurableFixtureDatabase = _DATABASE,
) -> AsyncIterator[DurableNotificationCase]:
    """One actual public case, with loop-independent app connections and a closed HTTP mock."""
    # Cohesive fixture exception: the one actual public case and its offline
    # request transcript share the same task-owned runtime factory lifetime.
    runtime = create_async_engine(
        qualified_durable_url(database).set(username="nexus_company_app"), poolclass=NullPool
    )
    requests: list[MockNotificationRequest] = []
    provider_id = uuid4()
    raw = json.dumps(
        {"id": str(provider_id)}
        if outcome == "accepted"
        else {
            "name": "validation_error" if outcome == "rejected" else "synthetic_ambiguous",
            "message": "synthetic rejected" if outcome == "rejected" else "synthetic ambiguous",
        },
        separators=(",", ":"),
    ).encode()
    status = {"accepted": 200, "rejected": 422, "unknown": 502}[outcome]

    def respond(request: httpx.Request) -> httpx.Response:
        value = MockNotificationRequest(
            method=request.method,
            path=request.url.path,
            idempotency_key=request.headers["Idempotency-Key"],
            body_sha256=hashlib.sha256(request.content).hexdigest(),
            response_sha256=hashlib.sha256(raw).hexdigest(),
        )
        requests.append(value)
        with (root / "mock-http-transcript.jsonl").open("a") as output:
            output.write(value.model_dump_json() + "\n")
        assert request.method == "POST" and request.url.path == "/emails" and len(requests) == 1
        return httpx.Response(status, content=raw)

    try:
        case = await atomic_notification_case(
            async_sessionmaker(runtime, expire_on_commit=False), root
        )
        case.services.dispatcher.configuration = NotificationTransportConfiguration(
            enabled=True,
            api_key=case.services.dispatcher.configuration.api_key,
            http_transport=httpx.MockTransport(respond),
        )
        services = replace(case.services, worker_id=uuid4())
        yield DurableNotificationCase(replace(case, services=services), requests)
    finally:
        await runtime.dispose()


async def sdk_notification_result(
    services: NotificationDispatchWorkerServices,
    command: SegmentCommand,
    *,
    root: Path,
    databases: AtomicNotificationDatabases,
    database: DurableFixtureDatabase = _DATABASE,
) -> NotificationSegmentResult:
    """SDK alone acquires ENQUEUED/PENDING; destroy only this created fixed worker before return."""
    # Cohesive lifecycle exception: constructor/launch/result and exact owned
    # thread/session shutdown evidence must remain one try/finally boundary.
    assert _dbos._dbos_global_instance is None and worker._services is None
    host_executor = capture_host_executor()
    url = qualified_durable_url(database).set(
        username="nexus_company_app", drivername="postgresql+psycopg"
    )
    try:
        (root / "sdk-startup-phase.json").write_text('{"phase":"before_constructor"}\n')
        worker.configure_notification_worker(services, url.render_as_string(hide_password=False))
        (root / "sdk-startup-phase.json").write_text('{"phase":"configured_before_launch"}\n')
        await worker.launch_notification_worker()
        (root / "sdk-startup-phase.json").write_text('{"phase":"launched_before_result"}\n')
        async with asyncio.timeout(30):
            raw = await DBOS.get_result_async(command.workflow_id)
        assert isinstance(raw, str)
        return NotificationSegmentResult.model_validate_json(raw)
    finally:
        if worker._services is services:
            instance = _dbos._get_dbos_instance()
            system_engine = worker._system_engine
            assert system_engine is not None
            launched = instance._launched
            threads = set(instance._background_threads)
            if instance._background_event_loop._thread is not None:
                threads.add(instance._background_event_loop._thread)
            if instance._executor_field is not None:
                threads.update(instance._executor_field._threads)
            await destroy_sdk_on_host_executor(host_executor)
            alive = [{"name": t.name, "ident": t.ident, "alive": t.is_alive()} for t in threads]
            await asyncio.to_thread(
                (root / "sdk-shutdown-proof.json").write_text,
                json.dumps(
                    {
                        "threads": alive,
                        "system_engine_disposed": False,
                        "application_backends": None,
                    },
                    indent=2,
                )
                + "\n",
            )
            assert (threads or not launched) and all(not t.is_alive() for t in threads)
            # Pinned SDK retains caller-supplied Engine ownership on destroy;
            # dispose only this exact worker pool after all owned threads stop.
            await asyncio.to_thread(system_engine.dispose)
            async with databases.admin() as session:
                sessions = await session.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                        "AND usename='nexus_company_app'"
                    )
                )
            await asyncio.to_thread(
                (root / "sdk-shutdown-proof.json").write_text,
                json.dumps(
                    {
                        "threads": alive,
                        "application_backends": sessions,
                        "system_engine_disposed": True,
                    },
                    indent=2,
                )
                + "\n",
            )
            assert sessions == 0
            worker._services = None
            worker._system_engine = None
        elif _dbos._dbos_global_instance is not None:
            # Preserve the original constructor exception and singleton presence;
            # local service globals being unset alone proves no SDK cleanup.
            (root / "sdk-constructor-failure-proof.json").write_text(
                json.dumps(
                    {
                        "sdk_global_present": True,
                        "local_services_unset": worker._services is None,
                        "limitation": "SDK singleton cleanup unproved; native DB preserved",
                    },
                    indent=2,
                )
                + "\n"
            )
