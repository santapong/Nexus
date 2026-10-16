"""Fixed qualification workflow: one native issuance, protected replay and owned release."""

import asyncio
from dataclasses import replace

from dbos import DBOS
from dbos._serialization import WorkflowSerializationFormat
from sqlalchemy import text

from nexus.core.llm.qualification_contracts import APPLICATION, QUEUE, VERSION, WORKFLOW
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.qualification_worker_context import (
    QualificationOperation,
    acquire_context,
    read_context,
    refresh_issued,
)
from nexus.execution.qualification_worker_recovery import (
    QualificationSegmentResult,
    recover_issued,
    segment_result,
)
from nexus.execution.qualification_worker_services import QualificationWorkerServices
from nexus.harness.qualification_client import QualificationClient, QualificationRunResult

_services: QualificationWorkerServices | None = None


def configure_qualification_worker(
    services: QualificationWorkerServices, system_database_url: str
) -> None:
    """Explicit server composition; no API payload can activate or reconfigure this worker."""
    global _services
    if _services is not None:
        raise ValueError("Qualification worker is already configured")
    services.require_composition()
    DBOS(
        config={
            "name": APPLICATION,
            "application_version": VERSION,
            "system_database_url": system_database_url,
            "run_migrations": False,
            "executor_id": str(services.worker_id),
            "enable_otlp": False,
            "use_listen_notify": False,
            "log_level": "WARNING",
            "sys_db_pool_size": 4,
            "max_executor_threads": 4,
        }
    )
    _services = services


async def launch_qualification_worker() -> None:
    """Launch only an explicitly configured restricted-role runtime and fixed single queue."""
    if _services is None:
        raise ValueError("Qualification worker services unavailable")
    _services.require_composition()
    async with _services.factory() as session:
        elevated = await session.scalar(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
        )
    if elevated is not False:
        raise ValueError("Qualification runtime must use its actual non-bypass role")
    DBOS.launch()
    await DBOS.register_queue_async(
        QUEUE, global_concurrency=1, worker_concurrency=1, polling_interval_sec=1.0
    )


@DBOS.workflow(name=WORKFLOW, serialization_type=WorkflowSerializationFormat.PORTABLE)
async def qualification_segment(payload: str) -> str:
    """Portable orchestration carries exact native IDs, no keys, prompt or permit."""
    SegmentCommand.model_validate_json(payload)
    return await qualification_step(payload)


@DBOS.step(name="nexus.model-qualification.effect.v1", retries_allowed=False)
async def qualification_step(payload: str) -> str:
    """No SDK retry or alternative API/provider after a committed native intent."""
    if _services is None or DBOS.workflow_id is None:
        raise ValueError("Qualification durable step services unavailable")
    command = SegmentCommand.model_validate_json(payload)
    result = await execute_qualification_segment(_services, command, workflow_id=DBOS.workflow_id)
    return result.model_dump_json()


async def _release(operation: QualificationOperation) -> None:
    """Release only after actual owners settle; no new cleanup deadline or late success."""
    await operation.settle()
    if operation.pending_owners() or operation.lease is None or operation.identity is None:
        return
    operation.require_current()
    await operation.call(
        operation.services.execution.release(
            operation.lease,
            operation.identity,
            blocked=operation.first is not None,
        )
    )
    operation.released = True


async def execute_qualification_segment(
    services: QualificationWorkerServices, command: SegmentCommand, *, workflow_id: str
) -> QualificationSegmentResult:
    """Inspect native/protected history first; caller and every pending resource keep ownership."""
    services.require_composition()
    if services.pending_owners() or any(item.running for item in services._operations.values()):
        raise ValueError("Qualification worker retains unsettled resources")
    operation = QualificationOperation(services)
    services._operations[workflow_id] = operation
    outcome: QualificationRunResult | None = None
    issued = None
    replayed = False
    try:
        context = await read_context(operation, command, workflow_id=workflow_id)
        issued = context.issued
        if context.issued is not None and context.issued.state in {"succeeded", "failed"}:
            replayed = True
            outcome = await recover_issued(operation, context, end_us=operation.end)
        else:
            client_end = await acquire_context(operation, context)
            issued = await operation.call(refresh_issued(operation, context))
            context = replace(context, issued=issued)
            if context.issued is not None:
                replayed = True
                outcome = await recover_issued(operation, context, end_us=client_end)
            else:
                assert operation.lease is not None
                operation.client = QualificationClient(
                    services.factory,
                    services.effects,
                    operation.lease,
                    context.credential.identity,
                    context.recipe,
                    context.request,
                    services.resolver,
                    services.evidence,
                    end_us=client_end,
                )
                # Direct await preserves the client's own first-cancellation semantics;
                # its actual SDK/file/receipt tasks remain reachable through operation.
                outcome = await operation.client.request_once()
        operation.require_current()
    except BaseException as error:
        operation.first = operation.first or error
        partial = error.__dict__.get("_nexus_qualification_result")
        if isinstance(partial, QualificationRunResult):
            outcome = partial
    try:
        await _release(operation)
    except BaseException as error:
        operation.first = operation.first or error
    pending = bool(operation.pending_owners())
    operation.running = False
    result = segment_result(
        command,
        outcome,
        replayed=replayed,
        failure=operation.first,
        pending=pending,
        released=operation.released,
        issued_record=issued,
    )
    try:
        result.model_dump_json()
        operation.require_current()
    except BaseException as error:
        operation.first = operation.first or error
        result = segment_result(
            command,
            outcome,
            replayed=replayed,
            failure=operation.first,
            pending=pending,
            released=operation.released,
            issued_record=issued,
        )
    if not pending:
        services._operations.pop(workflow_id, None)
    if isinstance(operation.first, asyncio.CancelledError):
        operation.first.__dict__["_nexus_qualification_segment"] = result
        operation.first.__dict__["_nexus_qualification_pending"] = operation.pending_owners()
        raise operation.first
    return result
