"""Fixed durable engineering procedures reconstruct trusted live services for each nonretry step."""

from datetime import UTC, datetime

from dbos import DBOS
from dbos._serialization import WorkflowSerializationFormat

from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.engineering_worker_context import (
    EngineeringContext,
    prepare_engineering_context,
)
from nexus.execution.engineering_worker_contracts import EngineeringSegmentResult
from nexus.execution.engineering_worker_effect import run_engineering_effect
from nexus.execution.engineering_worker_services import EngineeringWorkerServices

_services: EngineeringWorkerServices | None = None


def configure_engineering_worker(
    services: EngineeringWorkerServices, system_database_url: str
) -> None:
    """Trusted composition pins one DBOS application; requests cannot reconfigure it."""
    global _services
    if _services is not None:
        raise ValueError("Engineering worker is already configured")
    DBOS(
        config={
            "name": "nexus-native-engineering",
            "application_version": "v1",
            "system_database_url": system_database_url,
            "run_migrations": False,
            "executor_id": "nexus-engineering-v1-local",
            "enable_otlp": False,
            "use_listen_notify": False,
            "log_level": "WARNING",
            "sys_db_pool_size": 4,
            "max_executor_threads": 4,
        }
    )
    _services = services


async def launch_engineering_worker() -> None:
    """Register the fixed bounded queue without minting any caller authority."""
    if _services is None:
        raise ValueError("Engineering worker services unavailable")
    from sqlalchemy import text

    async with _services.factory() as session:
        elevated = await session.scalar(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
        )
    if elevated:
        raise ValueError("Engineering runtime cannot bypass company RLS")
    DBOS.launch()
    await DBOS.register_queue_async(
        "nexus.engineering.native",
        global_concurrency=1,
        worker_concurrency=1,
        polling_interval_sec=1.0,
    )


@DBOS.workflow(name="engineering.change", serialization_type=WorkflowSerializationFormat.PORTABLE)
async def engineering_change_segment(payload: str) -> str:
    """Fixed author procedure carries only its exact immutable native SegmentCommand."""
    return await engineering_effect_step(payload)


@DBOS.workflow(name="engineering.verify", serialization_type=WorkflowSerializationFormat.PORTABLE)
async def engineering_verify_segment(payload: str) -> str:
    """Fixed verifier procedure carries no caller result, permit or accepted verdict."""
    return await engineering_effect_step(payload)


@DBOS.step(name="nexus.engineering.effect.v1", retries_allowed=False)
async def engineering_effect_step(payload: str) -> str:
    """Current native I/O/fences live inside one durable nonretry effect boundary."""
    if _services is None or DBOS.workflow_id is None:
        raise ValueError("Engineering durable step services unavailable")
    command = SegmentCommand.model_validate_json(payload)
    return (
        await execute_engineering_segment(_services, command, workflow_id=DBOS.workflow_id)
    ).model_dump_json()


async def execute_engineering_segment(
    services: EngineeringWorkerServices, command: SegmentCommand, *, workflow_id: str
) -> EngineeringSegmentResult:
    """Known native output/acceptance remains separate from release and unknown billing."""
    context: EngineeringContext | None = None
    outcome: EngineeringSegmentResult | None = None
    failure: str | None = None
    try:
        context = await prepare_engineering_context(services, command, workflow_id=workflow_id)
        outcome = await run_engineering_effect(services, context)
    except Exception as exc:
        failure = type(exc).__name__
        if context is None:
            raise
    finally:
        if context is not None:
            released = await services.runner.execution.release(
                context.guard.lease, context.identity
            )
    if failure is not None:
        assert context is not None
        return EngineeringSegmentResult(
            company_id=command.company_id,
            command=command,
            phase=context.phase,
            workflow_name="engineering.change"
            if context.phase == "author"
            else "engineering.verify",
            status="outcome_unknown" if released.state == "outcome_unknown" else "blocked",
            billing="unconfirmed",
            observed_at=datetime.now(UTC),
            limitations=(failure, "mechanical_engineering_only", "business_readiness_unproven"),
        )
    assert outcome is not None
    return outcome
