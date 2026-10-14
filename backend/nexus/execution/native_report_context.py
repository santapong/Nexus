"""Actual native dispatch, immutable work pins and preverified actor before fenced execution."""

import asyncio
from dataclasses import dataclass

from sqlalchemy import func, select

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.report_inputs import native_author
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.native_report_services import NativeReportServices
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True)
class NativeReportContext:
    """Trusted live services/context are not checkpointable permits."""

    services: NativeReportServices
    command: SegmentCommand
    action: ActionProposal
    identity: VerifiedIdentity
    lease: ExecutionLease


async def prepare_context(
    services: NativeReportServices, command: SegmentCommand
) -> NativeReportContext:
    """Resolve a configured signed actor for actual native work, then recover the exact dispatch."""
    async with services.factory() as session, session.begin():
        await session.execute(
            select(func.set_config("nexus.company_id", str(command.company_id), True))
        )
        control = await session.scalar(
            select(CompanyControl)
            .where(CompanyControl.company_id == command.company_id)
            .with_for_update()
        )
        row = await session.get(ExecutionWork, (command.company_id, command.task_id))
        dispatch = await session.get(SegmentDispatch, (command.company_id, command.action_id))
        if (
            control is None
            or row is None
            or dispatch is None
            or dispatch.binding_json != command.model_dump_json()
            or dispatch.workflow_id != command.workflow_id
        ):
            raise ExecutionDeniedError("Native queued dispatch is unavailable")
        binding, _ = native_author(row)
        if (binding.workflow_name, binding.workflow_version) != (
            services.registration.workflow_name,
            services.registration.workflow_version,
        ):
            raise ExecutionDeniedError("Native queued work version is unregistered")
        signed = services.identities.actor(binding)
        if (signed.principal_id, signed.workspace_id) != (binding.actor_id, binding.workspace_id):
            raise ExecutionDeniedError("Native configured actor differs from actual work")
    scope = LedgerScope(
        company_id=command.company_id,
        principal_id=signed.principal_id,
        task_id=command.task_id,
        trace_id=command.trace_id,
    )
    command.require_scope(scope)
    action = (await CompanyJournal(services.factory).get_action(scope, command.action_id)).proposal
    lease = await recover_lease(services, scope, signed, command)
    return NativeReportContext(services, command, action, signed, lease)


async def recover_lease(
    services: NativeReportServices,
    scope: LedgerScope,
    identity: VerifiedIdentity,
    command: SegmentCommand,
) -> ExecutionLease:
    """Bounded wait for an actual previous lease; the same dispatch retains lifetime counters."""
    # M1 admits leases up to300s. An observation wait must cover that real
    # lifetime; thirty seconds could turn a recoverable dispatch into a cached
    # blocked workflow result while the original valid lease still exists.
    deadline = asyncio.get_running_loop().time() + 310
    while asyncio.get_running_loop().time() < deadline:
        try:
            return await services.execution.recover_dispatched(
                scope,
                identity,
                services.worker_id,
                command.segment_id,
                ttl_seconds=services.lease_ttl_seconds,
            )
        except ExecutionDeniedError:
            current = await services.execution.get(scope, identity)
            if current.worker_id is None or current.segment_id != command.segment_id:
                raise
            await asyncio.sleep(0.05)
    raise ExecutionDeniedError("Native prior lease did not release within bounded recovery wait")
