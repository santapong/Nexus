"""Registered durable native report/check procedure, with one non-retrying effect step."""

from dbos import DBOS
from dbos._serialization import WorkflowSerializationFormat
from sqlalchemy import text

from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.native_report_context import NativeReportContext, prepare_context
from nexus.execution.native_report_contracts import NativeReportResult
from nexus.execution.native_report_effect import run_native_effect
from nexus.execution.native_report_services import (
    NATIVE_APPLICATION,
    NATIVE_QUEUE,
    NATIVE_VERSION,
    NATIVE_WORKFLOW,
    NativeReportServices,
)

_services: NativeReportServices | None = None


def configure_native_report_worker(
    services: NativeReportServices, system_database_url: str
) -> None:
    """Configure fixed deployment/runtime services; no caller workflow/profile overrides."""
    global _services
    if _services is not None:
        raise ValueError("Native report worker is already configured")
    _services = services
    DBOS(
        config={
            "name": NATIVE_APPLICATION,
            "application_version": NATIVE_VERSION,
            "system_database_url": system_database_url,
            "run_migrations": False,
            "executor_id": services.executor_id,
            "enable_otlp": False,
            "use_listen_notify": False,
            "log_level": "WARNING",
            "sys_db_pool_size": 4,
            "max_executor_threads": 4,
        }
    )


async def launch_native_report_worker() -> None:
    """Launch the pinned durable runtime and register one bounded queue, without invoking models."""
    if _services is None:
        raise ValueError("Native report services are unavailable")
    async with _services.factory() as session:
        elevated = await session.scalar(
            text(
                "SELECT count(*) FROM pg_roles WHERE rolname=current_user "
                "AND (rolsuper OR rolbypassrls)"
            )
        )
        if elevated:
            raise ValueError("Native report business connections cannot bypass company RLS")
    DBOS.launch()
    await DBOS.register_queue_async(
        NATIVE_QUEUE,
        global_concurrency=1,
        worker_concurrency=1,
        polling_interval_sec=0.05,
    )


@DBOS.workflow(name=NATIVE_WORKFLOW, serialization_type=WorkflowSerializationFormat.PORTABLE)
async def native_report_segment(payload: str) -> str:
    """Deterministic orchestration; no cached permit or checkpointed dependency object."""
    SegmentCommand.model_validate_json(payload)
    return await native_report_step(payload)


@DBOS.step(name="nexus.native.report.effect.v1", retries_allowed=False)
async def native_report_step(payload: str) -> str:
    """Changing governance/lease/intent and invocation stay in one durable I/O step."""
    if _services is None or DBOS.workflow_id is None:
        raise ValueError("Native report step context is unavailable")
    command = SegmentCommand.model_validate_json(payload)
    return (
        await execute_native_report(_services, command, workflow_id=DBOS.workflow_id)
    ).model_dump_json()


async def execute_native_report(
    services: NativeReportServices,
    command: SegmentCommand,
    *,
    workflow_id: str,
) -> NativeReportResult:
    """Recover exact dispatch and release capacity, preserving unknown issued outcomes."""
    if workflow_id != command.workflow_id:
        raise ValueError("Native workflow identity differs from permanent dispatch")
    context: NativeReportContext | None = None
    outcome: NativeReportResult | None = None
    failure: str | None = None
    try:
        context = await prepare_context(services, command)
        outcome = await run_native_effect(context)
    except Exception as exc:
        # Return bounded failure facts; incomplete issuance remains durably unknown.
        failure = type(exc).__name__
    finally:
        if context is not None:
            released = await services.execution.release(
                context.lease, context.identity, blocked=failure is not None
            )
    if failure is not None:
        return NativeReportResult(
            company_id=command.company_id,
            task_id=command.task_id,
            action_id=command.action_id,
            segment_id=command.segment_id,
            status="outcome_unknown"
            if context is not None and released.state == "outcome_unknown"
            else "blocked",
            limitations=(failure, "native_mechanical_only", "business_readiness_unproven"),
        )
    assert outcome is not None
    return outcome
