"""One exact reviewed synthetic DBOS worker process; no providers, private repos or devices."""

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

from dbos import DBOS, WorkflowHandleAsync
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.engineering_worker import (
    configure_engineering_worker,
    launch_engineering_worker,
)
from nexus.execution.engineering_worker_services import EngineeringWorkerHook
from nexus.settings import settings
from nexus.tests.engineering_process_config import EngineeringProcessConfig
from nexus.tests.engineering_process_scope import require_process_root
from nexus.tests.engineering_process_services import compose_process_services


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument(
        "--barrier",
        choices=[
            "intent_committed",
            "result_stored",
            "receipt_recorded",
            "proof_registered",
            "acceptance_recorded",
        ],
    )
    return parser.parse_args()


def load_config(
    root: Path, database: str, workflow_id: str
) -> tuple[EngineeringProcessConfig, SegmentCommand]:
    """Bounded private reviewed files carry data only; exact command must match config."""
    for name in ["engineering-process-config.json", "engineering-command.json"]:
        path = root / name
        assert path.is_file() and not path.is_symlink() and path.stat().st_mode & 0o777 == 0o600
        assert path.stat().st_size <= 32768
    config = EngineeringProcessConfig.model_validate_json(
        (root / "engineering-process-config.json").read_bytes()
    )
    command = SegmentCommand.model_validate_json((root / "engineering-command.json").read_bytes())
    assert (
        config.command == command
        and command.workflow_id == workflow_id
        and config.database == database
    )
    return config, command


def observer(root: Path, barrier: str | None) -> EngineeringWorkerHook:
    """Trusted nominated phase waits only after its actual store method committed."""

    async def hook(phase: str, command: SegmentCommand) -> None:
        with (root / "phases.jsonl").open("a") as stream:
            stream.write(phase + "\n")
        if phase == barrier:
            (root / "barrier-reached.json").write_text(command.model_dump_json())
            while True:
                await asyncio.sleep(0.05)

    return hook


async def main() -> None:
    args = arguments()
    root = Path(args.root)
    url = make_url(settings.company_database_url)
    assert isinstance(url.database, str) and url.username == "nexus_company_app"
    require_process_root(url.database, root, existing=True)
    assert url.host is None and url.port is None and url.password is None
    assert dict(url.query) == {
        "host": "/tmp/nexus-release-tests-2026-10-13/socket",
        "port": "55438",
    }
    config, command = load_config(root, url.database, args.workflow_id)
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    hook = observer(root, args.barrier)
    services = compose_process_services(factory, config, root, command, UUID(args.worker_id), hook)
    configure_engineering_worker(
        services, url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
    )
    try:
        async with factory() as session:
            database = await session.scalar(text("SELECT current_database()"))
        (root / "runtime-database.txt").write_text(str(database))
        await launch_engineering_worker()
        handle: WorkflowHandleAsync[str] = await DBOS.retrieve_workflow_async(args.workflow_id)
        result = await asyncio.wait_for(handle.get_result(polling_interval_sec=0.05), timeout=120)
        sys.stdout.write("ENGINEERING_RESULT=" + result + "\n")
        sys.stdout.flush()
    finally:
        await asyncio.to_thread(DBOS.destroy, workflow_completion_timeout_sec=1)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
