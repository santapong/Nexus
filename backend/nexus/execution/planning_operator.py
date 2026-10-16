"""Three explicit local planning modes; existing finite actor and signer are prerequisites."""

from __future__ import annotations

import argparse
import asyncio
import signal

from dbos import DBOS
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.builder.contained_query import clock_us
from nexus.execution.planning_application import (
    PlanningApplication,
    compose_planning_application,
    planning_app,
)
from nexus.execution.planning_application_files import load_planning_config
from nexus.execution.planning_application_preflight import preflight_planning_database
from nexus.execution.planning_application_runtime import (
    PlanningWorkerRuntime,
    retire_planning_application,
    start_planning_application_worker,
)
from nexus.execution.qualification_application import (
    FiniteWorkerCredential,
    company_database_url,
    read_secret_fd,
    require_admin_database,
)
from nexus.settings import settings

PLANNING_MODES = frozenset({"planning-api", "planning-worker", "planning-migrate"})


def validate_planning_arguments(args: argparse.Namespace) -> None:
    """Reject cross-mode credentials and disposable inputs before opening a file or engine."""
    if (
        args.mode not in PLANNING_MODES
        or args.root is not None
        or args.qualification_config is not None
        or args.qualification_config_sha is not None
        or args.planning_config is None
        or args.planning_config_sha is None
        or not 1024 <= args.port <= 65535
        or args.sdk_receipt is not None
        or args.prompt_password
        or args.database_name is not None
        or args.docs_manifest is not None
        or args.docs_manifest_sha is not None
    ):
        raise ValueError("Planning needs exact config pins, local port and no disposable inputs")
    actor_mode = args.mode in {"planning-api", "planning-worker"}
    required = args.worker_credential_fd if actor_mode else args.admin_database_fd
    forbidden = args.admin_database_fd if actor_mode else args.worker_credential_fd
    if type(required) is not int or required < 0 or forbidden is not None:
        raise ValueError(
            "Planning needs only its exact inherited actor or administrator descriptor"
        )


def _serve(
    services: PlanningApplication,
    engine: AsyncEngine,
    args: argparse.Namespace,
    end_us: int,
) -> None:
    import uvicorn

    app = planning_app(services)

    async def startup() -> None:
        try:
            await preflight_planning_database(services, end_us=end_us)
        except BaseException as first:
            await _retire(services, engine, None, first)
            raise

    async def shutdown() -> None:
        await retire_planning_application(services, destroy=None, dispose=engine.dispose)

    app.on_startup.append(startup)
    app.on_shutdown.append(shutdown)
    uvicorn.run(app, host=args.host, port=args.port, access_log=False, log_level="warning")


async def _retire(
    services: PlanningApplication,
    engine: AsyncEngine,
    runtime: PlanningWorkerRuntime | None,
    first: BaseException | None = None,
) -> None:
    try:
        await retire_planning_application(
            services,
            destroy=runtime.destroy if runtime is not None else None,
            dispose=engine.dispose,
        )
    except BaseException as secondary:
        if first is None:
            raise
        first.__dict__["_nexus_planning_secondary"] = type(secondary).__name__


async def _run_worker(
    services: PlanningApplication,
    engine: AsyncEngine,
    system_url: str,
    end_us: int,
) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def stopping() -> None:
        services.lifecycle.request_stop()
        stop.set()

    installed: list[signal.Signals] = []
    runtime: PlanningWorkerRuntime | None = None
    first: BaseException | None = None
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stopping)
            installed.append(sig)
        await preflight_planning_database(services, end_us=end_us)
        runtime = await start_planning_application_worker(services, system_url)
        await stop.wait()
    except BaseException as error:
        first = error
        raise
    finally:
        try:
            await _retire(services, engine, runtime, first)
        finally:
            for sig in installed:
                loop.remove_signal_handler(sig)


def planning_mode(args: argparse.Namespace) -> None:
    """Operator acquisition is synchronous and bounded, outside the serving event loop."""
    validate_planning_arguments(args)
    end = clock_us() + 30_000_000
    frozen = load_planning_config(args.planning_config, args.planning_config_sha, end_us=end)
    url = company_database_url(settings)
    if args.mode == "planning-migrate":
        secret = read_secret_fd(args.admin_database_fd, limit=4096, end_us=end)
        admin = require_admin_database(secret.get_secret_value(), url)
        frozen.require_current(end_us=end)
        DBOS.migrate(
            admin.render_as_string(hide_password=False), application_role="nexus_company_app"
        )
        return
    original = read_secret_fd(args.worker_credential_fd, limit=16384, end_us=end)
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    services = compose_planning_application(
        factory,
        frozen.value,
        settings,
        FiniteWorkerCredential(original),
        SecretStr(settings.jwt_secret_key),
    )
    # Reacquisition is only operator startup, never an HTTP request or implicit refresh.
    frozen.require_current(end_us=end)
    if args.mode == "planning-api":
        _serve(services, engine, args, end)
        return
    asyncio.run(
        _run_worker(
            services,
            engine,
            url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
            end,
        )
    )
