"""Actual task-owned durable process with private phase barriers, no model or device effects."""

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

from dbos import DBOS, WorkflowHandleAsync
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.source_registry import SourcePolicy
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.native_report_composition import compose_native_reports
from nexus.execution.native_report_services import NativePhase
from nexus.execution.native_report_worker import (
    configure_native_report_worker,
    launch_native_report_worker,
)
from nexus.settings import settings
from nexus.tests.management_scheduler_support import FixtureIdentities, FixtureResources
from nexus.tests.native_process_config import NativeProcessConfig


class ProcessPolicies:
    """Exact operator policy configuration restored from the fixture's immutable registry file."""

    def __init__(self, policies: tuple[SourcePolicy, ...]) -> None:
        self.values = {row.source_symbol: row for row in policies}

    def policy(self, symbol: str) -> SourcePolicy:
        """Lookup supplies no caller policy or source location override."""
        return self.values[symbol]


async def main() -> None:
    """Launch actual registered DBOS native workflow and expose only bounded test result facts."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument(
        "--barrier",
        choices=(
            "intent_committed",
            "artifact_published",
            "receipt_recorded",
            "acceptance_recorded",
        ),
    )
    args = parser.parse_args()
    root = Path(args.root)
    config = NativeProcessConfig.model_validate_json(
        (root / "native-process-config.json").read_text()
    )
    url = make_url(settings.company_database_url)
    assert (
        url.database == "nexus_company_test_native_workflow" and url.username == "nexus_company_app"
    )
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def observe(phase: NativePhase, command: SegmentCommand) -> None:
        with (root / "phases.jsonl").open("a") as stream:
            stream.write(phase + "\n")
        if phase == args.barrier:
            (root / "barrier-reached").write_text(command.model_dump_json())
            while True:
                await asyncio.sleep(0.05)

    services = compose_native_reports(
        factory,
        catalog=config.catalog,
        blobs=ProtectedBlobStore(root / "blobs", storage_symbol="fixture.blobs.v1"),
        policies=ProcessPolicies(config.policies),
        rules=config.rules,
        identities=FixtureIdentities(),
        resources=FixtureResources(),
        worker_id=uuid4(),
        hook=observe,
        lease_ttl_seconds=60,
    )
    configure_native_report_worker(
        services, url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
    )
    try:
        await launch_native_report_worker()
        handle: WorkflowHandleAsync[str] = await DBOS.retrieve_workflow_async(args.workflow_id)
        result = await asyncio.wait_for(handle.get_result(polling_interval_sec=0.05), timeout=100)
        sys.stdout.write("NATIVE_RESULT=" + result + "\n")
        sys.stdout.flush()
    finally:
        await asyncio.to_thread(DBOS.destroy, workflow_completion_timeout_sec=1)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
