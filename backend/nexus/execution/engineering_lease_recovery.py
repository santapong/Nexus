"""Bounded same-dispatch acquisition wait never retries an engineering effect or credential."""

import asyncio
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.engineering_worker_services import EngineeringWorkerServices
from nexus.execution.management_checks import require_management_execution
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_recovery import dispatched_binding
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    require_runtime_scope,
    runtime_transaction,
)
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl, JournalAction

MAX_ACQUISITION_SECONDS = 310


async def prior_live_deadline(
    services: EngineeringWorkerServices,
    scope: LedgerScope,
    credential: AuthenticatedWorkerIdentity,
    command: SegmentCommand,
) -> datetime | None:
    """Current member/company lock and complete permanent command precede any acquisition wait."""
    if not isinstance(credential, AuthenticatedWorkerIdentity):
        raise ExecutionDeniedError("Engineering verified credential unavailable")
    command.require_scope(scope)
    identity = credential.identity
    if (identity.principal_id, identity.workspace_id) != (command.actor_id, command.workspace_id):
        raise ExecutionDeniedError("Engineering credential differs from dispatched actor")
    async with runtime_transaction(
        services.factory, scope, identity, allow_paused=True, allow_inactive=True
    ) as (session, control, _):
        work = await execution_row(session, scope)
        actual = await dispatched_binding(session, work, scope, command.segment_id)
        if actual != command:
            raise ExecutionDeniedError("Engineering permanent command differs")
        await require_wait_admission(session, control, services, scope, identity, command, work)
        final = await db_now(session)
        credential.require_time(final)
        if work.worker_id is not None and work.lease_until is not None and work.lease_until > final:
            if work.segment_id != command.segment_id:
                raise ExecutionDeniedError("Engineering prior lease belongs to another segment")
            return work.lease_until
        return None


async def require_wait_admission(
    session: AsyncSession,
    control: CompanyControl,
    services: EngineeringWorkerServices,
    scope: LedgerScope,
    identity: VerifiedIdentity,
    command: SegmentCommand,
    work: ExecutionWork,
) -> None:
    """Only an exact issued record permits historical waiting; fresh work retains all admission."""
    action = await session.get(JournalAction, command.action_id)
    if action is None:
        raise ExecutionDeniedError("Engineering wait action unavailable")
    require_journal_command(action, command)
    await require_exact_unresolved_basis(session, command)
    issued = await session.get(EffectIntent, (command.company_id, command.action_id))
    if issued is not None:
        if (issued.task_id, issued.trace_id, issued.run_id, issued.proposal_hash) != (
            command.task_id,
            command.trace_id,
            command.run_id,
            action.proposal_hash,
        ):
            raise ExecutionDeniedError("Engineering wait issued binding differs")
        return
    if control.paused:
        raise ExecutionDeniedError("Paused company cannot wait for a fresh engineering effect")
    await require_runtime_scope(
        session, control, scope, identity, allow_inactive=False, owner_read=False
    )
    await require_management_execution(
        session,
        control,
        work,
        identity,
        services.catalog,
        services.acceptance.inputs.reader,
        services.acceptance.inputs.freshness,
    )


async def require_exact_unresolved_basis(session: AsyncSession, command: SegmentCommand) -> None:
    """A different unresolved action cannot be treated as fresh or exact historical work."""
    unresolved = tuple(
        (
            await session.scalars(
                select(EffectIntent.action_id)
                .where(
                    EffectIntent.company_id == command.company_id,
                    EffectIntent.task_id == command.task_id,
                    EffectIntent.run_id == command.run_id,
                    EffectIntent.state.in_(("intent", "outcome_unknown")),
                )
                .limit(2)
            )
        ).all()
    )
    if any(action_id != command.action_id for action_id in unresolved):
        raise ExecutionDeniedError("Engineering wait has another unresolved issued action")


def require_journal_command(action: JournalAction, command: SegmentCommand) -> None:
    """Exact registered action bytes cannot be replaced by a merely matching segment."""
    proposal = ActionProposal.model_validate_json(action.proposal_json)
    if (
        proposal.company_id,
        proposal.task_id,
        proposal.trace_id,
        proposal.actor_id,
        proposal.action_id,
    ) != (
        command.company_id,
        command.task_id,
        command.trace_id,
        command.actor_id,
        command.action_id,
    ) or action.proposal_hash != action_hash(proposal):
        raise ExecutionDeniedError("Engineering wait journal binding differs")


async def require_current_credential(
    services: EngineeringWorkerServices, scope: LedgerScope, credential: AuthenticatedWorkerIdentity
) -> None:
    """Recheck current member and captured expiry without refreshing credentials."""
    async with runtime_transaction(
        services.factory, scope, credential.identity, allow_paused=True, allow_inactive=True
    ) as (session, _, _):
        credential.require_time(await db_now(session))


async def wait_prior(seconds: float) -> None:
    """A bounded asynchronous observation wait is cancellation-aware."""
    await asyncio.sleep(seconds)


async def recover_engineering_lease(
    services: EngineeringWorkerServices,
    scope: LedgerScope,
    credential: AuthenticatedWorkerIdentity,
    command: SegmentCommand,
) -> ExecutionLease:
    """Only acquisition retries; actual M1 still owns every fresh or known-issued effect gate."""
    limit = asyncio.timeout(MAX_ACQUISITION_SECONDS)
    try:
        async with limit:
            while True:
                deadline = await prior_live_deadline(services, scope, credential, command)
                if deadline is not None:
                    # Actual DB preflight validated that the deadline is still in the future.
                    # Poll at most once/second; a wallclock change cannot expand the total bound.
                    await wait_prior(1.0)
                    await require_current_credential(services, scope, credential)
                    continue
                try:
                    lease = await services.runner.execution.recover_dispatched(
                        scope,
                        credential.identity,
                        services.worker_id,
                        command.segment_id,
                        ttl_seconds=services.lease_ttl_seconds,
                    )
                except ExecutionDeniedError:
                    if await prior_live_deadline(services, scope, credential, command) is None:
                        raise
                    continue
                try:
                    await require_current_credential(services, scope, credential)
                except BaseException:
                    await services.runner.execution.release(lease, credential.identity)
                    raise
                return lease
    except TimeoutError:
        if not limit.expired():
            raise
        raise ExecutionDeniedError(
            "Engineering prior lease did not release within bounded acquisition"
        ) from None
