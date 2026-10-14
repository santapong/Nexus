"""TEST-only fixed SDK process; credentials remain in inherited pipes and memory."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import selectors
import stat
import time
from contextlib import suppress
from pathlib import Path
from uuid import UUID

from dbos import DBOS, _dbos
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.execution import notification_worker as worker
from nexus.execution.notification_worker_contracts import NotificationSegmentResult
from nexus.settings import settings
from nexus.tests.notification_acquisition_observer import install_notification_acquisition_observer
from nexus.tests.notification_durable_pg_fixture import (
    capture_host_executor,
    destroy_sdk_on_host_executor,
)
from nexus.tests.notification_preserved_history_support import (
    HistoricalOnlyBlobs,
    HistoricalOnlyDrafts,
)
from nexus.tests.notification_process_config import (
    NotificationProcessConfig,
    require_notification_process_root,
)
from nexus.tests.notification_process_services import compose_notification_process_services

CREDENTIAL_READ_TIMEOUT_SECONDS = 5.0


def read_worker_credential(fd: int) -> SecretStr:
    """Bounded FIFO only; close after read and sanitize errors."""
    if type(fd) is not int or fd < 3:
        raise ValueError("Notification process credential is unavailable")
    try:
        if not stat.S_ISFIFO(os.fstat(fd).st_mode):
            raise ValueError("Unsupported credential descriptor")
        os.set_blocking(fd, False)
        raw = bytearray()
        deadline = time.monotonic() + CREDENTIAL_READ_TIMEOUT_SECONDS
        with selectors.DefaultSelector() as selector:
            selector.register(fd, selectors.EVENT_READ)
            while len(raw) <= 8192:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ValueError("Credential pipe timeout")
                chunk = os.read(fd, 8193 - len(raw))
                if not chunk:
                    break
                raw.extend(chunk)
        value = bytes(raw).decode("ascii")
        if not 1 <= len(raw) <= 8192 or any(c.isspace() for c in value):
            raise ValueError("Credential envelope differs")
        return SecretStr(value)
    except (OSError, ValueError, UnicodeError):
        raise ValueError("Notification process credential is unavailable") from None
    finally:
        with suppress(OSError):
            os.close(fd)


class FixedPipeCredential:
    def __init__(self, value: SecretStr) -> None:
        self._value = value

    async def credential(self) -> SecretStr:
        return self._value


def read_process_config(root: Path, database: str) -> NotificationProcessConfig:
    """Exact owned0600 ordinary bounded config, no pickle/credential/namespace rewrite."""
    require_notification_process_root(database, root, existing=True)
    path = root / "notification-process-config.json"
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or not 1 <= info.st_size <= 1048576
        ):
            raise ValueError("Notification process config is unavailable")
        raw = os.read(fd, 1048577)
        assert len(raw) == info.st_size
    finally:
        os.close(fd)
    config = NotificationProcessConfig.model_validate_json(raw)
    if config.database != database or config.root != root:
        raise ValueError("Notification process config scope differs")
    return config


async def main() -> None:
    """Delegate native authority without migration, enqueue or freshening."""
    # Cohesive process lifecycle: actual verifier, fixed SDK and exact owned
    # thread/pool cleanup stay within one bounded worker with no external effects.
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--credential-fd", required=True, type=int)
    parser.add_argument("--barrier", choices=("intent", "response", "receipt", "observation"))
    args = parser.parse_args()
    url = make_url(settings.company_database_url)
    assert url.drivername == "postgresql+asyncpg" and url.username == "nexus_company_app"
    assert (
        url.password is None
        and url.host is None
        and url.port is None
        and isinstance(url.database, str)
    )
    assert dict(url.query) == {
        "host": "/tmp/nexus-release-tests-2026-10-13/socket",
        "port": "55438",
    }
    root = Path(args.root)
    config = read_process_config(root, url.database)
    if args.workflow_id != config.command.workflow_id:
        raise ValueError("Notification process workflow differs")
    credential = await asyncio.to_thread(read_worker_credential, args.credential_fd)
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    runtime = compose_notification_process_services(
        factory, config, FixedPipeCredential(credential), UUID(args.worker_id), args.barrier
    )
    witness = await runtime.services.reads.identities.current(
        expected_binding=config.registration.value.registration.sender
    )
    if (witness.issued_at, witness.expires_at) != (
        config.credential_issued_at,
        config.credential_expires_at,
    ):
        raise ValueError("Notification original credential window differs")
    if args.barrier is None:
        install_notification_acquisition_observer(root)
    host_executor = capture_host_executor()
    try:
        worker.configure_notification_worker(
            runtime.services,
            url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
        )
        await worker.launch_notification_worker()
        async with asyncio.timeout(90):
            raw = await DBOS.get_result_async(config.command.workflow_id)
        assert isinstance(raw, str)
        result = NotificationSegmentResult.model_validate_json(raw)
        output = root / f"worker-result-{args.worker_id}.json"
        output.write_text(result.model_dump_json())
        output.chmod(0o600)
    finally:
        if worker._services is runtime.services:
            instance = _dbos._get_dbos_instance()
            owned_engine = worker._system_engine
            assert owned_engine is not None
            threads = set(instance._background_threads)
            if instance._background_event_loop._thread is not None:
                threads.add(instance._background_event_loop._thread)
            if instance._executor_field is not None:
                threads.update(instance._executor_field._threads)
            await destroy_sdk_on_host_executor(host_executor)
            alive = [{"name": t.name, "ident": t.ident, "alive": t.is_alive()} for t in threads]
            failed_shutdown = root / f"worker-shutdown-{args.worker_id}.json"
            failed_shutdown.write_text(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "worker_id": args.worker_id,
                        "threads": alive,
                        "engine_disposed": False,
                        "other_app_backends": None,
                    },
                    indent=2,
                )
                + "\n"
            )
            failed_shutdown.chmod(0o600)
            assert all(not t.is_alive() for t in threads)
            await asyncio.to_thread(owned_engine.dispose)
            async with factory() as session:
                others = await session.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname=current_database() AND usename=current_user "
                        "AND pid<>pg_backend_pid()"
                    )
                )
            proof = {
                "pid": os.getpid(),
                "worker_id": args.worker_id,
                "threads": alive,
                "other_app_backends": others,
                "engine_disposed": True,
                "http_calls": runtime.http_calls,
                "blob_reads": runtime.blobs.reads
                if isinstance(runtime.blobs, HistoricalOnlyBlobs)
                else None,
                "draft_getter_reads": runtime.drafts.body_reads
                if isinstance(runtime.drafts, HistoricalOnlyDrafts)
                else None,
                "body_sql_attempts": runtime.sql_guard.body_sql_attempts
                if runtime.sql_guard
                else None,
            }
            path = root / f"worker-shutdown-{args.worker_id}.json"
            path.write_text(json.dumps(proof, indent=2) + "\n")
            path.chmod(0o600)
            assert others == 0
            worker._services = None
            worker._system_engine = None
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
