"""Resolve exact permanent engineering dispatch before current signed actor lease recovery."""

from dataclasses import dataclass

from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.plans import RunBinding
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.engineering_worker_contracts import EngineeringPhase
from nexus.execution.engineering_worker_identity import EngineeringCredentialSourceGuard
from nexus.execution.engineering_worker_services import EngineeringWorkerServices
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_contracts import LedgerScope


@dataclass(frozen=True)
class EngineeringContext:
    """Current lease/services can issue only through the existing native M1 runner."""

    command: SegmentCommand
    binding: RunBinding
    phase: EngineeringPhase
    action: ActionProposal
    spec: BuilderExecutionSpec
    identity: VerifiedIdentity
    lease: ExecutionLease
    guard: BuilderSourceGuard
    credential: AuthenticatedWorkerIdentity


async def prepare_engineering_context(
    services: EngineeringWorkerServices, command: SegmentCommand, *, workflow_id: str
) -> EngineeringContext:
    """Exact portable command never supplies an actor, source path or reusable execution permit."""
    if command.workflow_id != workflow_id:
        raise ValueError("Engineering workflow differs from permanent dispatch")
    from nexus.execution.engineering_dispatch_read import read_engineering_dispatch

    binding, phase, action, spec = await read_engineering_dispatch(services, command, workflow_id)
    credential = await services.identities.current(binding)
    if not isinstance(credential, AuthenticatedWorkerIdentity):
        raise ValueError("Engineering authenticated credential witness unavailable")
    signed = credential.identity
    if (signed.principal_id, signed.workspace_id) != (binding.actor_id, binding.workspace_id):
        raise ValueError("Engineering configured signed actor differs")
    scope = LedgerScope(
        company_id=command.company_id,
        principal_id=signed.principal_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
    )
    command.require_scope(scope)
    async with services.factory() as clock:
        credential.require_time(await db_now(clock))
    lease = await services.runner.execution.recover_dispatched(
        scope,
        signed,
        services.worker_id,
        command.segment_id,
        ttl_seconds=services.lease_ttl_seconds,
    )
    try:
        guard = EngineeringCredentialSourceGuard(
            services.sources.resolve(binding, spec, lease, signed), credential
        )
        services.runner.require_binding(lease, signed, spec, guard)
        return EngineeringContext(
            command, binding, phase, action, spec, signed, lease, guard, credential
        )
    except BaseException:
        # This acquisition is real even if a context object was never returned.
        # Current fencing still owns release; a failed release must propagate.
        await services.runner.execution.release(lease, signed)
        raise
