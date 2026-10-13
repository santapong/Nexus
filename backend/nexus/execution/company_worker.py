"""Registered offline company segment: one fresh non-retrying effect step.

This first integrated adapter deliberately uses an ordinary pre-registered
TestModel inside one DBOS I/O step. It does not claim Pydantic AI durability
capability replay or production per-request provider harness conformance.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from dbos import DBOS
from dbos._serialization import WorkflowSerializationFormat
from pydantic import TypeAdapter
from pydantic_ai import Agent
from sqlalchemy import func, select, text

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.base import Name
from nexus.execution.company_worker_contracts import WorkerResult
from nexus.execution.company_worker_effect import EffectContext, run_effect
from nexus.execution.company_worker_support import (
    MODEL_PROFILE,
    MODEL_REGISTRY_VERSION,
    DraftParameters,
    OfflineWorkerServices,
    offline_agent,
)
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dbos_queue import (
    APPLICATION_NAME,
    APPLICATION_VERSION,
    QUEUE_NAME,
    WORKFLOW_NAME,
)
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import (
    ExecutionDeniedError,
    ExecutionLease,
    ExecutionSnapshot,
)
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl

_services: OfflineWorkerServices | None = None
_agent: Agent[None, str] | None = None


def configure_company_worker(
    services: OfflineWorkerServices,
    system_database_url: str,
    *,
    application_version: str = APPLICATION_VERSION,
) -> None:
    """Configure the trusted deployment version before launch; never a command override."""
    global _services, _agent
    if _services is not None:
        raise ValueError("Company worker is already configured in this process")
    application_version = TypeAdapter(Name).validate_python(application_version)
    _services, _agent = services, offline_agent()
    DBOS(
        config={
            "name": APPLICATION_NAME,
            "application_version": application_version,
            "system_database_url": system_database_url,
            "run_migrations": False,
            "executor_id": "nexus-company-offline-worker-v1",
            "enable_otlp": False,
            "use_listen_notify": False,
            "log_level": "WARNING",
            "sys_db_pool_size": 4,
            "max_executor_threads": 4,
        }
    )


async def launch_company_worker() -> None:
    """Launch then register the one bounded queue using pinned DBOS 3.2 async APIs."""
    if _services is None:
        raise ValueError("Company worker must be configured before launch")
    async with _services.factory() as session:
        elevated = await session.scalar(
            text(
                "SELECT count(*) FROM pg_roles WHERE rolname = current_user "
                "AND (rolsuper OR rolbypassrls)"
            )
        )
        if elevated:
            raise ValueError("Business connections must not bypass company RLS")
    DBOS.launch()
    await DBOS.register_queue_async(
        QUEUE_NAME, global_concurrency=1, worker_concurrency=1, polling_interval_sec=0.05
    )


@DBOS.workflow(name=WORKFLOW_NAME, serialization_type=WorkflowSerializationFormat.PORTABLE)
async def company_segment(payload: str) -> str:
    """Deterministic workflow body; all I/O and changing authority stay inside its one step."""
    SegmentCommand.model_validate_json(payload)
    return await execute_segment(payload)


@DBOS.step(name="company.action.effect.v1", retries_allowed=False)
async def execute_segment(payload: str) -> str:
    """Never checkpoint a fresh permission separately from its invocation/receipt."""
    if _services is None or _agent is None:
        raise ValueError("Company worker dependencies are unavailable")
    command = SegmentCommand.model_validate_json(payload)
    if DBOS.workflow_id != command.workflow_id:
        raise ValueError("Workflow ID differs from permanent dispatch identity")
    context: EffectContext | None = None
    result: WorkerResult | None = None
    released: ExecutionSnapshot | None = None
    failure: str | None = None
    try:
        context = await _prepare_effect(_services, _agent, command)
        result = await run_effect(context)
    except (ValueError, ExecutionDeniedError) as exc:
        failure = type(exc).__name__
    finally:
        if context is not None:
            released = await context.execution.release(
                context.lease, context.identity, blocked=failure is not None
            )
    if failure is not None:
        return WorkerResult(
            company_id=command.company_id,
            task_id=command.task_id,
            action_id=command.action_id,
            segment_id=command.segment_id,
            status="outcome_unknown"
            if released is not None and released.state == "outcome_unknown"
            else "blocked",
            limitations=(failure,),
        ).model_dump_json()
    assert result is not None
    return result.model_dump_json()


async def _prepare_effect(
    services: OfflineWorkerServices, agent: Agent[None, str], command: SegmentCommand
) -> EffectContext:
    """Resolve trusted registered inputs before the single fenced effect sequence."""
    scope = LedgerScope(
        company_id=command.company_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
        principal_id=command.actor_id,
    )
    identity = VerifiedIdentity(principal_id=command.actor_id, workspace_id=command.workspace_id)
    execution, effects = ExecutionStore(services.factory), EffectStore(services.factory)
    owner = await _validate_dispatch(services, command)
    current = await execution.get(scope, identity)
    if (current.registration.model_profile, current.registration.model_registry_version) != (
        MODEL_PROFILE,
        MODEL_REGISTRY_VERSION,
    ):
        raise ValueError("Offline worker model catalog binding is unavailable")
    action = (await CompanyJournal(services.factory).get_action(scope, command.action_id)).proposal
    _validate_tool(action)
    lease = await _recover(execution, scope, identity, command)
    return EffectContext(
        services, agent, execution, effects, lease, identity, command, action, owner
    )


async def _validate_dispatch(services: OfflineWorkerServices, command: SegmentCommand) -> UUID:
    async with services.factory() as session, session.begin():
        await session.execute(
            select(func.set_config("nexus.company_id", str(command.company_id), True))
        )
        control = await session.scalar(
            select(CompanyControl)
            .where(CompanyControl.company_id == command.company_id)
            .with_for_update()
        )
        dispatch = await session.get(SegmentDispatch, (command.company_id, command.action_id))
        if (
            control is None
            or dispatch is None
            or (
                dispatch.binding_json != command.model_dump_json()
                or dispatch.workflow_id != command.workflow_id
            )
        ):
            raise ValueError("Stored dispatch differs from the queued command")
        return control.owner_id


def _validate_tool(action: ActionProposal) -> None:
    allowed = {
        ("fake.internal.draft.v1", "v1", "fixture:report"),
        ("fake.internal.read.v1", "v1", "fixture:source"),
    }
    if (action.tool, action.tool_version, action.resource) not in allowed:
        raise ValueError("Offline worker cannot invoke this tool/version/resource")
    if action.tool == "fake.internal.draft.v1":
        DraftParameters.model_validate(action.parameters)
    elif action.parameters:
        raise ValueError("Offline read accepts no client path or source override")


async def _recover(
    execution: ExecutionStore,
    scope: LedgerScope,
    identity: VerifiedIdentity,
    command: SegmentCommand,
) -> ExecutionLease:
    assert _services is not None
    for _ in range(600):
        try:
            return await execution.recover_dispatched(
                scope,
                identity,
                _services.worker_id,
                command.segment_id,
                ttl_seconds=_services.lease_ttl_seconds,
            )
        except ExecutionDeniedError:
            snapshot = await execution.get(scope, identity)
            if snapshot.worker_id is None or snapshot.segment_id != command.segment_id:
                raise
            await asyncio.sleep(0.05)
    raise ExecutionDeniedError("Previous worker lease did not release within bounded recovery wait")
