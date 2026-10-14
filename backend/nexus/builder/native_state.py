"""Actual M1 scope/action/intent/fence reads; data alone grants no execution authority."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.execution.effect_support import require_effect_authority
from nexus.execution.runtime_contracts import EffectRecord, ExecutionLease
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import JournalAction


async def actual_action(
    factory: async_sessionmaker[AsyncSession],
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    action: ActionProposal,
    spec: BuilderExecutionSpec,
) -> tuple[EffectIntent | None, datetime]:
    async with runtime_transaction(
        factory, lease_scope(lease), identity, allow_paused=True, allow_inactive=True
    ) as (session, _, _):
        work = await execution_row(session, lease_scope(lease))
        now = await db_now(session)
        require_lease(work, lease, now)
        row = await session.get(JournalAction, spec.job.action_id)
        if (
            row is None
            or row.company_id != lease.company_id
            or ActionProposal.model_validate_json(row.proposal_json) != action
            or row.proposal_hash != action_hash(action)
        ):
            raise ValueError("Builder actual native action differs")
        if (
            spec.job.company_id,
            spec.job.task_id,
            spec.job.trace_id,
            spec.job.run_id,
            spec.job.actor_id,
            spec.job.workspace_id,
        ) != (
            work.company_id,
            work.task_id,
            work.trace_id,
            work.run_id,
            work.actor_id,
            work.workspace_id,
        ):
            raise ValueError("Builder actual native work differs")
        if (
            action.tool != "company.builder.run.v1"
            or action.tool_version != "v1"
            or action.resource != spec.job.resource_symbol
            or action.parameters != spec.model_dump(mode="json")
        ):
            raise ValueError("Builder actual proposal does not bind its descriptor")
        return await session.get(EffectIntent, (work.company_id, action.action_id)), now


async def current_source(
    factory: async_sessionmaker[AsyncSession],
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    action: ActionProposal,
    guard: BuilderSourceGuard,
    *,
    issued: bool,
) -> None:
    async with runtime_transaction(factory, lease_scope(lease), identity) as (session, control, _):
        work = await execution_row(session, lease_scope(lease))
        now = await db_now(session)
        require_lease(work, lease, now, execute=True)
        row = await require_effect_authority(
            session, control, work, action.action_id, now, (), lease_scope(lease), identity
        )
        if issued:
            intent = await session.get(EffectIntent, (work.company_id, action.action_id))
            if intent is None or (
                intent.state,
                intent.intent_fence,
                intent.run_id,
                intent.proposal_hash,
            ) != ("intent", lease.fence, lease.run_id, action_hash(action)):
                raise ValueError("Builder current intent/fence is unavailable")
        await guard.validate(session, control, work, row, now)
        final = await db_now(session)
        require_lease(work, lease, final, execute=True)
        guard.validate_time(final)


async def result_disclosure(
    factory: async_sessionmaker[AsyncSession],
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    guard: BuilderSourceGuard,
) -> bool:
    try:
        async with runtime_transaction(
            factory, lease_scope(lease), identity, allow_paused=True, allow_inactive=True
        ) as (session, control, _):
            await guard.disclosure_windows(session, control)
        return True
    except ValueError:
        return False


def require_record_result(record: EffectRecord, proposal_sha256: str, run_id: UUID) -> None:
    if record.proposal_hash != proposal_sha256 or record.run_id != run_id:
        raise ValueError("Builder known result differs from actual native intent")
