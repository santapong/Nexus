"""Actual journal/execution/budget source snapshots, without caller status or amount inputs."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.native_fact_contracts import (
    BlockedState,
    CapSelector,
    CompanyCapState,
    DecisionState,
    WorkCapState,
)
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.contracts.results import ActionReceipt
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.cancellation_support import cancellation_for_work
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.report_input_contracts import native_author
from nexus.company.management.scheduling_reads import inspect_task
from nexus.execution.effect_support import require_receipt_binding
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import snapshot
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_models import (
    CompanyControl,
    CostHold,
    DailyBudget,
    JournalAction,
    WorkBudget,
)
from nexus.harness.journal_submission import pending_action_record


async def actual_work(session: AsyncSession, company_id: UUID, task_id: UUID) -> ExecutionWork:
    """A registered native work row is required; IDs cannot create or rebind work."""
    row = await session.get(ExecutionWork, (company_id, task_id))
    if row is None:
        raise BrainDeniedError("Native fact registered work is unavailable")
    native_author(row)
    return row


async def decision_state(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    action_id: UUID,
) -> DecisionState | None:
    row = await session.get(JournalAction, action_id)
    if row is None or row.company_id != scope.company_id:
        raise BrainDeniedError("Native pending decision is unavailable")
    record = pending_action_record(row)
    if record.approval is not None or record.state.value != "awaiting_approval":
        return None
    work = await actual_work(session, scope.company_id, row.task_id)
    bound = await ManagementPlanStore.current_binding(session, scope.company_id, row.task_id)
    if bound is None or (
        record.proposal.task_id,
        record.proposal.trace_id,
        record.proposal.actor_id,
    ) != (work.task_id, work.trace_id, work.actor_id):
        raise BrainDeniedError("Native pending action/work binding is no longer current")
    return DecisionState(
        company_id=scope.company_id,
        action=record,
        work=bound.child.binding,
        registration_sha256=work.registration_hash,
        plan=bound.plan,
        policy_version=control.policy_version,
        price_version=control.price_version,
    )


async def blocked_state(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    task_id: UUID,
    services: NativeFactServices,
) -> BlockedState | None:
    work = await actual_work(session, scope.company_id, task_id)
    candidate = await inspect_task(session, control, work, identity, services.scheduler)
    if candidate.projection.eligibility.state not in {"blocked", "cancelled"}:
        return None
    return BlockedState(
        company_id=scope.company_id,
        work=native_author(work)[0],
        registration_sha256=work.registration_hash,
        execution=snapshot(work),
        eligibility=candidate.projection.eligibility,
        cancellation=await cancellation_for_work(
            session, scope.company_id, task_id, trace_id=work.trace_id, run_id=work.run_id
        ),
    )


async def cap_state(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    selector: CapSelector,
    now: datetime,
) -> CompanyCapState | WorkCapState | None:
    if selector.task_id is None:
        day = billing_day(now)
        row = await session.get(DailyBudget, (scope.company_id, day))
        if row is None or row.held_usd + row.spent_usd < control.daily_cap_usd:
            return None
        return CompanyCapState(
            company_id=scope.company_id,
            budget_day=day,
            cap_usd=control.daily_cap_usd,
            held_usd=row.held_usd,
            spent_usd=row.spent_usd,
            billing_unknown=await unknown_billing(session, scope.company_id, None),
            policy_version=control.policy_version,
        )
    work = await actual_work(session, scope.company_id, selector.task_id)
    registered = await session.get(RegisteredWork, (scope.company_id, work.task_id))
    budget = await session.get(WorkBudget, (scope.company_id, work.task_id))
    if registered is None or budget is None:
        raise BrainDeniedError("Native own work cap is unavailable")
    cap = min(registered.allocation_usd, control.work_cap_usd)
    if budget.held_usd + budget.spent_usd + registered.delegated_usd < cap:
        return None
    return WorkCapState(
        company_id=scope.company_id,
        work=native_author(work)[0],
        root_task_id=registered.root_task_id,
        allocation_usd=registered.allocation_usd,
        cap_usd=cap,
        delegated_usd=registered.delegated_usd,
        held_usd=budget.held_usd,
        spent_usd=budget.spent_usd,
        billing_unknown=await unknown_billing(session, scope.company_id, work.task_id),
        policy_version=control.policy_version,
    )


async def unknown_billing(session: AsyncSession, company_id: UUID, task_id: UUID | None) -> bool:
    statement = (
        select(CostHold.action_id)
        .where(CostHold.company_id == company_id, CostHold.state == "unknown")
        .limit(1)
    )
    if task_id is not None:
        statement = statement.where(CostHold.task_id == task_id)
    return await session.scalar(statement) is not None


async def failed_receipt_state(
    session: AsyncSession, scope: BrainReadScope, action_id: UUID
) -> ActionReceipt | None:
    """Failure wake requires actual failed M1 outcome, never a worker observation/candidate flag."""
    row = await session.get(EffectIntent, (scope.company_id, action_id))
    if row is None or row.receipt_json is None:
        return None
    receipt = ActionReceipt.model_validate_json(row.receipt_json)
    work = await actual_work(session, scope.company_id, row.task_id)
    require_receipt_binding(row, receipt)
    if (row.task_id, row.trace_id, row.run_id) != (work.task_id, work.trace_id, work.run_id):
        raise BrainDeniedError("Native failed receipt differs from the exact registered run")
    return receipt if row.state == "failed" and receipt.outcome == "failed" else None
