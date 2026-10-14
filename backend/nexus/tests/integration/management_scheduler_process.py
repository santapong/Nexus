"""Private real DBOS queue/recovery probe; claim/release only, no model, effect or acceptance."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID, uuid4

from dbos import DBOS, WorkflowHandleAsync
from dbos._serialization import WorkflowSerializationFormat
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.management_checks import require_management_execution
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import runtime_transaction
from nexus.harness.journal_contracts import LedgerScope
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import COMPANY
from nexus.tests.management_plan_support import registered_freshness
from nexus.tests.management_scheduler_support import (
    APPLICATION,
    QUEUE,
    VERSION,
    WORKFLOW,
    FixtureIdentities,
)

_factory: async_sessionmaker[AsyncSession] | None = None
_runtime: ExecutionStore | None = None
_catalog: PlanAdmissionCatalog | None = None
_artifacts: BoundedArtifactReader | None = None
_root: Path | None = None
_barrier: bool = False
_worker_id: UUID = uuid4()


@DBOS.workflow(name=WORKFLOW, serialization_type=WorkflowSerializationFormat.PORTABLE)
async def observe_delivery(payload: str) -> str:
    """Only portable exact SegmentCommand enters this real registered queue workflow."""
    return await claim_and_release(payload)


@DBOS.step(name="management.scheduler.claim-only.v1", retries_allowed=False)
async def claim_and_release(payload: str) -> str:
    """A replay reclaims the existing same segment; it never creates effect permission."""
    assert _runtime is not None and _root is not None
    command = SegmentCommand.model_validate_json(payload)
    if DBOS.workflow_id != command.workflow_id or command.company_id != COMPANY:
        raise ValueError("Private workflow is not the exact fixture dispatch")
    signed = await actual_identity(command)
    scope = LedgerScope(
        company_id=command.company_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
        principal_id=signed.principal_id,
    )
    lease = await _runtime.recover_dispatched(
        scope, signed, _worker_id, command.segment_id, ttl_seconds=2
    )
    await asyncio.to_thread(record_lease, _root, lease)
    if _barrier:
        while True:
            await asyncio.sleep(0.05)
    released = await _runtime.release(lease, signed)
    return released.model_dump_json()


async def actual_identity(command: SegmentCommand) -> VerifiedIdentity:
    """Resolve predetermined actual actor identity and check current plan/native dispatch."""
    assert _factory is not None and _catalog is not None and _artifacts is not None
    async with _factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        binding = await ManagementPlanStore.current_binding(session, COMPANY, command.task_id)
    if binding is None:
        raise ValueError("Private workflow has no current native child")
    signed = FixtureIdentities().actor(binding.child.binding)
    scope = LedgerScope(
        company_id=COMPANY,
        task_id=command.task_id,
        trace_id=command.trace_id,
        principal_id=signed.principal_id,
    )
    async with runtime_transaction(_factory, scope, signed) as (session, control, _):
        from nexus.execution.runtime_models import ExecutionWork

        work = await session.get(ExecutionWork, (COMPANY, command.task_id))
        dispatch = await session.get(SegmentDispatch, (COMPANY, command.action_id))
        if (
            work is None
            or dispatch is None
            or dispatch.binding_json != payload_json(command)
            or dispatch.workflow_id != command.workflow_id
        ):
            raise ValueError("Private workflow differs from permanent native dispatch")
        await require_management_execution(
            session, control, work, signed, _catalog, _artifacts, registered_freshness(_factory)
        )
    return signed


def payload_json(command: SegmentCommand) -> str:
    return command.model_dump_json()


def record_lease(root: Path, lease: ExecutionLease) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "leases.jsonl").open("a") as stream:
        stream.write(lease.model_dump_json() + "\n")
    (root / "claimed").write_text(lease.model_dump_json())


async def main() -> None:
    global _factory, _runtime, _catalog, _artifacts, _root, _barrier
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--barrier", action="store_true")
    args = parser.parse_args()
    _root, _barrier = Path(args.root), args.barrier
    url = make_url(settings.company_database_url)
    assert url.database == "nexus_company_test_management_scheduler"
    assert url.username == "nexus_company_app"
    engine = create_async_engine(url)
    _factory = async_sessionmaker(engine, expire_on_commit=False)
    _catalog = PlanAdmissionCatalog.model_validate_json(
        await asyncio.to_thread((_root / "catalog.json").read_text)
    )
    _artifacts = BoundedArtifactReader(
        _factory, ProtectedBlobStore(_root / "blobs", storage_symbol="fixture.blobs.v1")
    )
    _runtime = ExecutionStore(
        _factory,
        management_catalog=_catalog,
        management_artifacts=_artifacts,
        management_freshness=registered_freshness(_factory),
    )
    DBOS(
        config={
            "name": APPLICATION,
            "application_version": VERSION,
            "system_database_url": url.set(drivername="postgresql+psycopg").render_as_string(
                hide_password=False
            ),
            "run_migrations": False,
            "executor_id": "management-scheduler-fixture-v1",
            "enable_otlp": False,
            "use_listen_notify": False,
            "log_level": "WARNING",
            "sys_db_pool_size": 3,
            "max_executor_threads": 3,
        }
    )
    try:
        DBOS.launch()
        await DBOS.register_queue_async(
            QUEUE, global_concurrency=1, worker_concurrency=1, polling_interval_sec=0.05
        )
        handle: WorkflowHandleAsync[str] = await DBOS.retrieve_workflow_async(args.workflow_id)
        result = await asyncio.wait_for(handle.get_result(polling_interval_sec=0.05), timeout=25)
        sys.stdout.write("SCHEDULER_RESULT=" + result + "\n")
        sys.stdout.flush()
    finally:
        await asyncio.to_thread(DBOS.destroy, workflow_completion_timeout_sec=1)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
