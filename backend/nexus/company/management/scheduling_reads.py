"""Current native bounded work/acceptance reads; no models or prepared actions are created."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.management.cancellation_support import cancellation_for_work
from nexus.company.management.control_support import db_clock
from nexus.company.management.operations import EligibilityReason, EligibilityState
from nexus.company.management.plan_models import ManagementVerificationBinding
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.scheduling_projection import projection, stale_projection
from nexus.company.management.scheduling_support import SchedulerServices, SchedulingCandidate
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.management_checks import current_accepted_work, require_management_execution
from nexus.execution.runtime_contracts import AttemptKind
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_store import next_segment_id
from nexus.execution.runtime_support import require_runtime_scope, snapshot
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl, CostHold, DailyBudget, JournalAction


async def _action(session: AsyncSession, work: ExecutionWork) -> JournalAction | None:
    query = select(JournalAction).where(
        JournalAction.company_id == work.company_id,
        JournalAction.task_id == work.task_id,
        JournalAction.trace_id == work.trace_id,
        JournalAction.state == "authorized",
        JournalAction.consumed_at.is_not(None),
        JournalAction.id.not_in(
            select(EffectIntent.action_id).where(
                EffectIntent.company_id == work.company_id,
            )
        ),
    )
    if work.waiting_action_id is not None:
        query = query.where(JournalAction.id == work.waiting_action_id)
    rows = tuple((await session.scalars(query.order_by(JournalAction.id).limit(2))).all())
    if len(rows) > 1:
        raise ManagementDeniedError("A work segment has ambiguous prepared actions")
    return rows[0] if rows else None


def action_kind(tool: str) -> AttemptKind:
    return "model_requests" if tool == "model.request.v1" else "tool_attempts"


async def _existing_dispatch(session: AsyncSession, work: ExecutionWork) -> SegmentDispatch | None:
    row: SegmentDispatch | None = await session.scalar(
        select(SegmentDispatch).where(
            SegmentDispatch.company_id == work.company_id,
            SegmentDispatch.task_id == work.task_id,
            SegmentDispatch.run_id == work.run_id,
            SegmentDispatch.segment_id == next_segment_id(snapshot(work)),
        )
    )
    return row


async def _uncertain(session: AsyncSession, work: ExecutionWork) -> EligibilityReason | None:
    effect = await session.scalar(
        select(EffectIntent.action_id)
        .where(
            EffectIntent.company_id == work.company_id,
            EffectIntent.task_id == work.task_id,
            EffectIntent.state.in_(("intent", "outcome_unknown")),
        )
        .limit(1)
    )
    if effect is not None or work.state == "outcome_unknown":
        return "outcome_unknown"
    hold = await session.scalar(
        select(CostHold.action_id)
        .where(
            CostHold.company_id == work.company_id,
            CostHold.task_id == work.task_id,
            CostHold.state == "unknown",
        )
        .limit(1)
    )
    return "billing_unknown" if hold is not None else None


async def _initial_reason(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    owner: VerifiedIdentity,
    services: SchedulerServices,
) -> tuple[EligibilityState, EligibilityReason] | None:
    if (
        await cancellation_for_work(
            session, work.company_id, work.task_id, trace_id=work.trace_id, run_id=work.run_id
        )
        is not None
    ):
        return "cancelled", "work_cancelled"
    if control.paused:
        return "blocked", "company_paused"
    accepted = await current_accepted_work(
        session, control, work, work, owner, services.artifacts, services.freshness
    )
    if accepted is not None:
        return "waiting", "already_accepted"
    uncertain = await _uncertain(session, work)
    if uncertain is not None:
        return "blocked", uncertain
    now = await db_clock(session)
    if work.worker_id is not None or (work.lease_until and work.lease_until > now):
        return "waiting", "dispatch_active"
    if work.state in {"running", "verifying"}:
        return "waiting", "dispatch_active"
    if work.state == "blocked":
        return "blocked", "scope_unavailable"
    return None


async def _prerequisites(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    binding: CurrentPlanBinding,
    owner: VerifiedIdentity,
    services: SchedulerServices,
) -> EligibilityReason | None:
    for task_id in binding.work.depends_on:
        dependency = await session.get(ExecutionWork, (work.company_id, task_id))
        if (
            dependency is None
            or await current_accepted_work(
                session, control, work, dependency, owner, services.artifacts, services.freshness
            )
            is None
        ):
            return "dependency_unaccepted"
    trigger = await session.get(
        ManagementVerificationBinding,
        (work.company_id, binding.plan.plan_revision_id, work.task_id),
    )
    if trigger is not None:
        effect = await session.scalar(
            select(EffectIntent.action_id)
            .where(
                EffectIntent.company_id == work.company_id,
                EffectIntent.task_id == trigger.author_task_id,
                EffectIntent.state == "succeeded",
                EffectIntent.receipt_json.is_not(None),
            )
            .limit(1)
        )
        if effect is None:
            return "verification_unbound"
    return None


async def inspect_task(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    owner: VerifiedIdentity,
    services: SchedulerServices,
) -> SchedulingCandidate:
    """Only native current registration and independent proof can make work eligible."""
    binding = await ManagementPlanStore.current_binding(session, work.company_id, work.task_id)
    if binding is None:
        stopped = await cancellation_for_work(
            session, work.company_id, work.task_id, trace_id=work.trace_id, run_id=work.run_id
        )
        projected = await stale_projection(session, work, cancelled=stopped is not None)
        return SchedulingCandidate(work, None, projected)
    initial = await _initial_reason(session, control, work, owner, services)
    if initial is not None:
        return SchedulingCandidate(work, binding, projection(work, binding, *initial))
    dependency = await _prerequisites(session, control, work, binding, owner, services)
    if dependency is not None:
        return SchedulingCandidate(work, binding, projection(work, binding, "waiting", dependency))
    identity = services.identities.actor(binding.child.binding)
    scope = LedgerScope(
        company_id=work.company_id,
        principal_id=work.actor_id,
        task_id=work.task_id,
        trace_id=work.trace_id,
    )
    try:
        await require_runtime_scope(
            session, control, scope, identity, allow_inactive=False, owner_read=False
        )
        await require_management_execution(
            session,
            control,
            work,
            identity,
            services.catalog,
            services.artifacts,
            services.freshness,
        )
    except ValueError:
        return SchedulingCandidate(
            work, binding, projection(work, binding, "blocked", "source_unavailable")
        )
    return await _available_action(session, control, work, binding, identity, scope)


async def _available_action(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    binding: CurrentPlanBinding,
    identity: VerifiedIdentity,
    scope: LedgerScope,
) -> SchedulingCandidate:
    """Waits and own reserved slices are read without acquiring a worker or minting costs."""
    existing = await _existing_dispatch(session, work)
    if existing is not None:
        result = projection(work, binding, "waiting", "dispatch_active").model_copy(
            update={
                "dispatch": "existing",
                "action_id": existing.action_id,
                "segment_id": existing.segment_id,
                "workflow_id": existing.workflow_id,
            }
        )
        return SchedulingCandidate(work, binding, result)
    action = await _action(session, work)
    if action is None:
        return SchedulingCandidate(
            work, binding, projection(work, binding, "waiting", "approval_pending")
        )
    from nexus.company.contracts.actions import ActionProposal

    proposed = ActionProposal.model_validate_json(action.proposal_json)
    kind = action_kind(proposed.tool)
    if getattr(work, f"{kind}_used") + getattr(work, f"{kind}_delegated") >= getattr(
        work, f"{kind}_limit"
    ):
        return SchedulingCandidate(
            work, binding, projection(work, binding, "blocked", "budget_exhausted")
        )
    hold = await session.get(CostHold, action.id)
    day = await session.get(DailyBudget, (work.company_id, billing_day(await db_clock(session))))
    if (
        hold is None
        or hold.state != "held"
        or (day and day.held_usd + day.spent_usd > control.daily_cap_usd)
    ):
        return SchedulingCandidate(
            work, binding, projection(work, binding, "blocked", "budget_exhausted")
        )
    return SchedulingCandidate(
        work, binding, projection(work, binding, "eligible", "ready"), action, identity, scope
    )
