"""Explicit local C modes; absent role input is closed denial, never another role's token."""

from __future__ import annotations

import argparse
import asyncio
import signal
from typing import TYPE_CHECKING

from dbos import DBOS
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.builder.contained_query import clock_us
from nexus.company.notifications.worker_identity import (
    OpaqueCredentialProvider,
    WorkerIdentityDeniedError,
)
from nexus.execution.coding_application_files import load_coding_config
from nexus.execution.qualification_application import (
    FiniteWorkerCredential,
    company_database_url,
    read_secret_fd,
    require_admin_database,
)
from nexus.settings import settings

if TYPE_CHECKING:
    from nexus.execution.coding_application import CodingApplication
    from nexus.execution.planning_application_runtime import PlanningWorkerRuntime

CODING_MODES = frozenset({"coding-api", "coding-worker", "coding-migrate"})


class UnavailableCredential:
    """No token/witness, no owner substitute or refresh; only fresh role work is denied."""

    async def credential(self) -> SecretStr:
        raise WorkerIdentityDeniedError("Configured role credential is unavailable")


def validate_coding_arguments(args: argparse.Namespace) -> None:
    """No credential contents/time/key availability is a prerequisite for owner/history boot."""
    if (
        args.mode not in CODING_MODES
        or args.coding_config is None
        or args.coding_config_sha is None
        or not 1024 <= args.port <= 65535
    ):
        raise ValueError("Coding needs exact server config and local port")
    actors = (args.planning_credential_fd, args.coding_credential_fd)
    if any(
        fd is not None and (type(fd) is not int or fd < 0)
        for fd in (*actors, args.admin_database_fd)
    ):
        raise ValueError("Coding inherited descriptor is invalid")
    if args.mode == "coding-migrate":
        if any(fd is not None for fd in actors) or args.admin_database_fd is None:
            raise ValueError("Coding migration needs only its explicit administrative descriptor")
    elif args.admin_database_fd is not None or (actors[0] is not None and actors[0] == actors[1]):
        raise ValueError("Coding actor descriptors must be separate and administrator-free")


def _credential(fd: int | None, end_us: int) -> OpaqueCredentialProvider:
    return (
        UnavailableCredential()
        if fd is None
        else FiniteWorkerCredential(read_secret_fd(fd, limit=16384, end_us=end_us))
    )


async def _retire(
    value: CodingApplication,
    engine: AsyncEngine,
    runtime: PlanningWorkerRuntime | None,
    first: BaseException | None = None,
) -> None:
    from nexus.execution.coding_application_runtime import retire_coding_application

    try:
        await retire_coding_application(
            value, destroy=runtime.destroy if runtime else None, dispose=engine.dispose
        )
    except BaseException as secondary:
        if first is None:
            raise
        first.__dict__["_nexus_coding_secondary"] = type(secondary).__name__


def _serve(
    value: CodingApplication, engine: AsyncEngine, args: argparse.Namespace, end_us: int
) -> None:
    import uvicorn

    from nexus.execution.coding_application import coding_app
    from nexus.execution.coding_application_preflight import preflight_coding_database
    from nexus.execution.coding_application_runtime import retire_coding_application

    app = coding_app(value)

    async def startup() -> None:
        try:
            await preflight_coding_database(value, end_us=end_us)
        except BaseException as first:
            await _retire(value, engine, None, first)
            raise

    async def shutdown() -> None:
        await retire_coding_application(value, destroy=None, dispose=engine.dispose)

    app.on_startup.append(startup)
    app.on_shutdown.append(shutdown)
    uvicorn.run(app, host=args.host, port=args.port, access_log=False, log_level="warning")


async def _run_worker(
    value: CodingApplication, engine: AsyncEngine, system_url: str, end_us: int
) -> None:
    from nexus.execution.coding_application_preflight import preflight_coding_database
    from nexus.execution.coding_application_runtime import start_coding_application_worker

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed = []
    runtime = None
    first = None

    def stopping() -> None:
        value.planning.lifecycle.request_stop()
        value.lifecycle.request_stop()
        stop.set()

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stopping)
            installed.append(sig)
        await preflight_coding_database(value, end_us=end_us)
        runtime = await start_coding_application_worker(value, system_url)
        await stop.wait()
    except BaseException as error:
        first = error
        raise
    finally:
        try:
            await _retire(value, engine, runtime, first)
        finally:
            for sig in installed:
                loop.remove_signal_handler(sig)


def coding_mode(args: argparse.Namespace) -> None:
    """Only bounded operator startup reads config/optional FDs; no account/signer creation."""
    from nexus.execution.coding_application import compose_coding_application

    validate_coding_arguments(args)
    end = clock_us() + 30_000_000
    frozen = load_coding_config(args.coding_config, args.coding_config_sha, end_us=end)
    url = company_database_url(settings)
    if args.mode == "coding-migrate":
        secret = read_secret_fd(args.admin_database_fd, limit=4096, end_us=end)
        admin = require_admin_database(secret.get_secret_value(), url)
        frozen.require_current(end_us=end)
        DBOS.migrate(
            admin.render_as_string(hide_password=False), application_role="nexus_company_app"
        )
        return
    planning = _credential(args.planning_credential_fd, end)
    coding = _credential(args.coding_credential_fd, end)
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        value = compose_coding_application(
            factory, frozen.value, settings, planning, coding, SecretStr(settings.jwt_secret_key)
        )
        frozen.require_current(end_us=end)
    except BaseException:
        asyncio.run(engine.dispose())
        raise
    if args.mode == "coding-api":
        _serve(value, engine, args, end)
        return
    asyncio.run(
        _run_worker(
            value,
            engine,
            url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
            end,
        )
    )
