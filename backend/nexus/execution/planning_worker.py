"""Fixed registered planning worker; protected historical output is never company completion."""

from __future__ import annotations

import asyncio
from typing import Literal
from uuid import UUID

from dbos import DBOS
from dbos._serialization import WorkflowSerializationFormat
from sqlalchemy import text

from nexus.builder.contained_query import clock_us
from nexus.company.brain.base import SHA256, Name, ValueContract
from nexus.company.contracts.actions import ResourceRevision
from nexus.company.management.planning_consumer import RegisteredPlanningConsumer
from nexus.company.management.planning_content import PlanningAttempt
from nexus.company.management.planning_prepared_contracts import (
    StoredPlanningRequest,
)
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.planning_history import NativePlanningHistory, native_history
from nexus.execution.planning_services import (
    APPLICATION,
    CLIENT_SECONDS,
    ENTRY_SECONDS,
    LEASE_SECONDS,
    QUEUE,
    VERSION,
    WORKFLOW,
    PlanningOperation,
    PlanningServices,
    clock_now,
)
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    require_lease,
    runtime_transaction,
)
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.model_client_contracts import GovernedModelCancelledError


class PlanningSegmentResult(ValueContract):
    """Path-free durable metadata; owner review reads protected bytes through its own gates."""

    command: SegmentCommand
    status: Literal["historical_candidate", "known_history", "outcome_unknown", "blocked"]
    native_state: Literal["intent", "outcome_unknown", "succeeded", "failed"] | None = None
    request_sha256: SHA256 | None = None
    receipt_id: UUID | None = None
    artifact_id: UUID | None = None
    artifact_sha256: SHA256 | None = None
    replayed: bool = False
    resources_pending: bool = False
    lease_released: bool = False
    error_type: Name | None = None
    company_completed: Literal[False] = False


def _cancelled_attempt(error: GovernedModelCancelledError) -> PlanningAttempt:
    """Retain the actual denied outcome; cancellation can never carry a candidate."""
    return PlanningAttempt(governed=error.governed, candidate=None, denial="model_outcome")


def _result(
    command: SegmentCommand,
    operation: PlanningOperation,
    history: NativePlanningHistory | None,
    attempt: PlanningAttempt | None,
    *,
    replayed: bool,
) -> PlanningSegmentResult:
    if attempt is None and isinstance(operation.first, GovernedModelCancelledError):
        attempt = _cancelled_attempt(operation.first)
    effect = history.effect if history else None
    recorded = attempt.governed.recorded if attempt else None
    candidate = attempt.candidate if attempt else None
    artifact = (
        recorded.artifact
        if recorded
        else (
            effect.receipt.artifacts[0]
            if effect and effect.receipt and effect.receipt.artifacts
            else None
        )
    )
    receipt_id = (
        recorded.receipt_id
        if recorded
        else (effect.receipt.receipt_id if effect and effect.receipt else None)
    )
    status: Literal["historical_candidate", "known_history", "outcome_unknown", "blocked"] = (
        "blocked"
    )
    if effect is not None:
        status = "known_history" if effect.state in {"succeeded", "failed"} else "outcome_unknown"
    if recorded is not None:
        status = "known_history" if recorded.billing == "known" else "outcome_unknown"
    if candidate is not None:
        status = "historical_candidate"
    if (
        attempt is not None
        and attempt.denial is not None
        and recorded is not None
        and recorded.billing == "known"
    ):
        status = "blocked"
    if operation.first is not None or operation.pending_owners():
        status = "outcome_unknown" if effect is not None or attempt is not None else "blocked"
    native_state = (
        effect.state
        if effect
        else (
            ("succeeded" if not recorded.stop_required else "failed")
            if recorded is not None and recorded.billing == "known"
            else None
        )
    )
    return PlanningSegmentResult(
        command=command,
        status=status,
        native_state=native_state,
        request_sha256=history.request_sha256 if history else None,
        receipt_id=receipt_id,
        artifact_id=artifact.artifact_id if artifact else None,
        artifact_sha256=artifact.sha256 if artifact else None,
        replayed=replayed,
        resources_pending=bool(operation.pending_owners()),
        lease_released=operation.released,
        error_type=type(operation.first).__name__
        if operation.first
        else (attempt.denial if attempt else None),
    )


async def _resources(
    operation: PlanningOperation,
    scope: LedgerScope,
    loaded: StoredPlanningRequest,
) -> tuple[ResourceRevision, ...]:
    services, credential, lease = operation.services, operation.credential, operation.lease
    assert credential is not None and lease is not None
    async with runtime_transaction(services.factory, scope, credential.identity) as (
        session,
        control,
        _,
    ):
        work = await execution_row(session, scope)
        require_lease(work, lease, await db_now(session), execute=True)
        required = await services.contexts.revalidate_context(
            session,
            control,
            loaded.prepared.scope,
            credential.identity,
            loaded.prepared.context.manifest,
            await db_now(session),
        )
        credential.require_time(await db_now(session))
        operation.require_admission()
    operation.require_current()
    return required


async def execute_planning_segment(
    services: PlanningServices,
    command: SegmentCommand,
    *,
    workflow_id: str,
    end_us: int,
) -> PlanningSegmentResult:
    """Native replay first; fresh actual witness/lease/prepared input can make only one request."""
    if workflow_id != command.workflow_id:
        raise ValueError("Planning workflow differs from its permanent dispatch")
    operation = PlanningOperation(services, workflow_id, end_us)
    history: NativePlanningHistory | None = None
    attempt: PlanningAttempt | None = None
    replayed = False
    try:
        history = await operation.call(native_history(services, command))
        if history.effect is not None:
            replayed = True  # No token/key/body read, lease or provider retry on issued history.
        else:
            credential = await operation.call(services.identities.current())
            operation.credential = credential
            if (credential.identity.principal_id, credential.identity.workspace_id) != (
                command.actor_id,
                command.workspace_id,
            ):
                raise ValueError("Planning worker needs its original actual actor witness")
            scope = LedgerScope(
                company_id=command.company_id,
                principal_id=command.actor_id,
                task_id=command.task_id,
                trace_id=command.trace_id,
            )
            now = await operation.call(clock_now(services))
            credential.require_time(now)
            ttl = min(
                LEASE_SECONDS,
                int((credential.expires_at - now).total_seconds()) - 1,
                (operation.end - clock_us()) // 1_000_000 - 1,
            )
            if ttl < 1:
                raise ValueError("Original planning witness/window cannot cover a lease")
            operation.require_admission()
            operation.lease_task = asyncio.create_task(
                services.execution.recover_dispatched(
                    scope,
                    credential.identity,
                    services.worker_id,
                    command.segment_id,
                    ttl_seconds=ttl,
                )
            )
            lease = await operation.call(operation.lease_task)
            operation.lease = lease
            history = await operation.call(native_history(services, command))
            if history.effect is not None:
                replayed = True  # An earlier worker may finish during acquisition; still no SDK.
            else:
                if lease.mode != "execute" or lease.expires_at > credential.expires_at:
                    raise ValueError("Planning fresh request lacks its own original execute window")
                loaded = await operation.call(
                    services.prepared.load_worker(
                        lease, credential.identity, command.action_id, end_us=operation.end
                    )
                )
                operation.end = min(operation.end, loaded.read_end_us)
                anchor = clock_us()
                now = await operation.call(clock_now(services))
                credential.require_time(now)
                operation.shorten(now, anchor, (lease.expires_at, credential.expires_at))
                sdk_end = min(operation.end - 5_000_000, clock_us() + CLIENT_SECONDS * 1_000_000)
                operation.require_admission()
                # load_worker already performed current source READ. Exact live Brain
                # conditions plus its saved descriptor condition are rechecked at intent.
                required = await operation.call(_resources(operation, scope, loaded))
                operation.consumer = RegisteredPlanningConsumer(
                    services.factory,
                    services.management.catalog.models,
                    services.resolver,
                    services.management,
                    services.contexts,
                    services.evidence,
                    services.estimator,
                    services.recipe,
                    lease,
                    credential.identity,
                    resources=(*required, loaded.reference.condition),
                    allowed_classification=loaded.prepared.request.data_classification,
                    model_observations=services.management.catalog.model_observations,
                    authenticated_actor=credential,
                    end_us=operation.end,
                    sdk_end_us=sdk_end,
                )
                operation.require_admission()
                # Direct orchestration preserves client stop semantics; its actual
                # SDK/FS/native leaves remain reachable through this operation.
                attempt = await operation.consumer.request_once(loaded.prepared, now=now)
                operation.released = attempt.governed.release_status == "released"
        operation.require_current()
    except BaseException as first:
        operation.first = operation.first or first
        if isinstance(first, GovernedModelCancelledError):
            attempt = _cancelled_attempt(first)
            operation.released = first.governed.release_status == "released"
    try:
        await operation.retire()
    except BaseException as secondary:
        operation.first = operation.first or secondary
    result = _result(command, operation, history, attempt, replayed=replayed)
    try:
        result.model_dump_json()
        operation.require_current()
    except BaseException as first:
        operation.first = operation.first or first
        result = _result(command, operation, history, attempt, replayed=replayed)
    operation.finish()
    if isinstance(operation.first, asyncio.CancelledError):
        operation.first.__dict__["_nexus_planning_result"] = result
        raise operation.first
    return result


_services: PlanningServices | None = None


def configure_planning_worker(services: PlanningServices, system_database_url: str) -> None:
    """Explicit opt-in only; no goal/account/approval creation or automatic DB migration."""
    global _services
    if _services is not None:
        raise ValueError("Planning worker is already configured")
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
        }
    )
    _services = services


async def launch_planning_worker() -> None:
    """Only the fixed queue, with an explicitly configured restricted-role database."""
    if _services is None:
        raise ValueError("Planning worker is not explicitly configured")
    _services.require_accepting()
    async with _services.factory() as session:
        elevated = await session.scalar(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
        )
    if elevated is not False:
        raise ValueError("Planning runtime requires its actual non-bypass role")
    DBOS.listen_queues([QUEUE])
    DBOS.launch()
    await DBOS.register_queue_async(
        QUEUE, global_concurrency=1, worker_concurrency=1, polling_interval_sec=1.0
    )


@DBOS.workflow(name=WORKFLOW, serialization_type=WorkflowSerializationFormat.PORTABLE)
async def planning_segment(payload: str) -> str:
    SegmentCommand.model_validate_json(payload)
    return await planning_step(payload)


@DBOS.step(name="nexus.planning.effect.v1", retries_allowed=False)
async def planning_step(payload: str) -> str:
    if _services is None or DBOS.workflow_id is None:
        raise ValueError("Planning worker is not explicitly configured")
    command = SegmentCommand.model_validate_json(payload)
    result = await execute_planning_segment(
        _services,
        command,
        workflow_id=DBOS.workflow_id,
        end_us=clock_us() + ENTRY_SECONDS * 1_000_000,
    )
    return result.model_dump_json()
