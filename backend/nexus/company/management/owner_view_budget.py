"""Read real ledgers once per action; inherited lifetime slices are not daily spend."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.directory_models import RegisteredWork
from nexus.company.management.control_support import db_clock
from nexus.company.management.owner_view_contracts import (
    CompanyBudget,
    DailyAllowance,
    LifetimeAllowance,
)
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import snapshot
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_models import CompanyControl, CostHold, DailyBudget, WorkBudget
from nexus.harness.limits import LoopCounters


@dataclass(frozen=True)
class ActualAmounts:
    known: Decimal
    reserved: Decimal
    unconfirmed: bool


async def actual_amounts(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork | None = None,
) -> ActualAmounts:
    if work is not None and work.company_id != control.company_id:
        raise ManagementDeniedError("Work cost company differs")
    issued = select(EffectIntent.action_id).where(EffectIntent.company_id == control.company_id)
    query = select(
        func.coalesce(func.sum(CostHold.actual_usd), 0),
        func.coalesce(
            func.sum(case((CostHold.state.in_(("held", "unknown")), CostHold.amount_usd), else_=0)),
            0,
        ),
        func.count(
            case(
                (
                    CostHold.actual_usd.is_(None)
                    & ((CostHold.state == "unknown") | CostHold.action_id.in_(issued)),
                    CostHold.action_id,
                )
            )
        ),
    ).where(CostHold.company_id == control.company_id)
    if work is not None:
        query = query.where(CostHold.task_id == work.task_id)
    known, reserved, missing = (await session.execute(query)).one()
    return ActualAmounts(Decimal(known), Decimal(reserved), bool(missing))


async def company_budget(session: AsyncSession, control: CompanyControl) -> CompanyBudget:
    day = billing_day(await db_clock(session))
    ledger = await session.get(DailyBudget, (control.company_id, day))
    held, spent = (ledger.held_usd, ledger.spent_usd) if ledger else (Decimal(0), Decimal(0))
    allocated = await session.scalar(
        select(func.coalesce(func.sum(RegisteredWork.allocation_usd), 0)).where(
            RegisteredWork.company_id == control.company_id,
            RegisteredWork.parent_task_id.is_(None),
        )
    )
    amounts = await actual_amounts(session, control)
    if allocated is None:
        raise ManagementDeniedError("Root lifetime allocation aggregate is unavailable")
    return CompanyBudget(
        daily=DailyAllowance(
            day=day,
            cap_usd=control.daily_cap_usd,
            held_usd=held,
            spent_usd=spent,
            available_usd=max(Decimal(0), control.daily_cap_usd - held - spent),
        ),
        current_work_cap_usd=control.work_cap_usd,
        root_lifetime_allocated_usd=Decimal(allocated),
        known_spent_usd=amounts.known,
        reserved_any_day_usd=amounts.reserved,
        actual_total_usd=None if amounts.unconfirmed else amounts.known,
        billing_unconfirmed=amounts.unconfirmed,
    )


async def lifetime_budget(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
) -> LifetimeAllowance:
    native = await session.get(RegisteredWork, (control.company_id, work.task_id))
    if native is None or work.company_id != control.company_id:
        raise ManagementDeniedError("Lifetime work allowance is unavailable")
    ledger = await session.get(WorkBudget, (control.company_id, work.task_id))
    held, spent = (ledger.held_usd, ledger.spent_usd) if ledger else (Decimal(0), Decimal(0))
    actual = await actual_amounts(session, control, work)
    state = snapshot(work)
    return LifetimeAllowance(
        root_task_id=native.root_task_id,
        parent_task_id=native.parent_task_id,
        allocated_usd=native.allocation_usd,
        delegated_usd=native.delegated_usd,
        own_ledger_held_usd=held,
        own_ledger_spent_usd=spent,
        own_known_spent_usd=actual.known,
        own_reserved_usd=actual.reserved,
        own_actual_total_usd=None if actual.unconfirmed else actual.known,
        own_billing_unconfirmed=actual.unconfirmed,
        limits=state.registration.quota,
        consumed=state.counters,
        delegated=LoopCounters(
            model_requests=work.model_requests_delegated,
            tool_attempts=work.tool_attempts_delegated,
            rework_rounds=work.rework_rounds_delegated,
            plan_revisions=work.plan_revisions_delegated,
        ),
    )
