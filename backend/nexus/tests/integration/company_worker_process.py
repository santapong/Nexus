"""Private acceptance process; test barriers are server hooks, never command privileges."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

from dbos import DBOS, WorkflowHandleAsync
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.company.contracts.actions import ResourceRevision
from nexus.execution.company_worker import configure_company_worker, launch_company_worker
from nexus.execution.company_worker_support import OfflineWorkerServices, WorkerPhase
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dbos_queue import APPLICATION_VERSION
from nexus.settings import settings


class ProcessHooks:
    """Write synthetic local evidence and optionally wait for deliberate process termination."""

    def __init__(self, root: Path, barrier: str | None, fault_phase: WorkerPhase | None) -> None:
        self.root, self.barrier = root, barrier
        self.fault_phase = fault_phase

    async def __call__(self, phase: WorkerPhase, command: SegmentCommand) -> None:
        await asyncio.to_thread(self._record, phase, command)
        if phase == self.fault_phase:
            raise ValueError("Trusted offline post-model fault injection")
        if phase == self.barrier:
            while True:
                await asyncio.sleep(0.05)

    def _record(self, phase: str, command: SegmentCommand) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "events.jsonl").open("a") as stream:
            stream.write(json.dumps({"phase": phase, "action_id": str(command.action_id)}) + "\n")
        (self.root / phase).write_text(str(command.action_id))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--barrier")
    parser.add_argument("--resource-version", default="offline-v1")
    parser.add_argument("--application-version", default=APPLICATION_VERSION)
    parser.add_argument("--observation-seconds", type=float)
    parser.add_argument("--fault-phase", choices=("model_called",))
    args = parser.parse_args()
    if args.observation_seconds is not None and not 0 < args.observation_seconds <= 10:
        raise ValueError("Private unmatched observation must be bounded to ten seconds")
    url = make_url(settings.company_database_url)
    assert url.database == "nexus_company_test_worker" and url.username == "nexus_company_app"
    engine = create_async_engine(url)
    services = OfflineWorkerServices(
        async_sessionmaker(engine, expire_on_commit=False),
        Path(args.artifacts),
        uuid4(),
        lease_ttl_seconds=2,
        hook=ProcessHooks(Path(args.evidence), args.barrier, args.fault_phase),
        resources=(ResourceRevision(resource="fixture:report", revision=args.resource_version),),
    )
    configure_company_worker(
        services,
        url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
        application_version=args.application_version,
    )
    try:
        await launch_company_worker()
        handle: WorkflowHandleAsync[str] = await DBOS.retrieve_workflow_async(args.workflow_id)
        result = await result_line(handle, args.workflow_id, args.observation_seconds)
        sys.stdout.write(result + "\n")
        sys.stdout.flush()
    finally:
        await asyncio.to_thread(DBOS.destroy, workflow_completion_timeout_sec=1)
        await engine.dispose()


async def result_line(
    handle: WorkflowHandleAsync[str], workflow_id: str, observation_seconds: float | None
) -> str:
    """A private bounded unmatched probe polls the same SDK handle without starting work."""
    if observation_seconds is None:
        result = await asyncio.wait_for(handle.get_result(polling_interval_sec=0.05), timeout=40)
        return "WORKER_RESULT=" + result
    try:
        result = await asyncio.wait_for(
            handle.get_result(polling_interval_sec=0.05), timeout=observation_seconds
        )
    except TimeoutError:
        return "WORKER_UNMATCHED=" + json.dumps(
            {
                "workflow_id": workflow_id,
                "application_version": DBOS.application_version,
                "observation_seconds": observation_seconds,
            }
        )
    raise AssertionError(f"Incompatible worker unexpectedly completed the workflow: {result}")


if __name__ == "__main__":
    asyncio.run(main())
