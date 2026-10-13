"""Move only an unissued reservation to its actual effect billing day."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.directory_models import RegisteredWork
from nexus.harness.journal_budget import billing_day, budget_rows
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl, CostHold, DailyBudget, WorkBudget


async def hold_to_effect_day(
    session: AsyncSession,
    control: CompanyControl,
    scope: LedgerScope,
    action_id: UUID,
    now: datetime,
) -> None:
    """Caller holds CompanyControl first and has proved no effect intent exists.

    Waiting across midnight must not spend a previous day's remaining allowance.
    Unknown/issued billing retains its original reservation and is reconciled
    separately; this helper cannot refund or reissue such an effect.
    """
    hold = await session.scalar(
        select(CostHold).where(
            CostHold.company_id == scope.company_id,
            CostHold.task_id == scope.task_id,
            CostHold.action_id == action_id,
        )
    )
    if hold is None or hold.state != "held" or hold.actual_usd is not None:
        raise ValueError("Unissued effect requires its unresolved held reservation")
    day = billing_day(now)
    original = await session.get(DailyBudget, (scope.company_id, hold.day))
    if original is None or original.held_usd < hold.amount_usd:
        raise ValueError("Original daily reservation disagrees with the hold")
    current, _ = await budget_rows(session, scope, day)
    transfer = Decimal(0) if hold.day == day else hold.amount_usd
    if current.held_usd + current.spent_usd + transfer > control.daily_cap_usd:
        raise ValueError("Current company daily allowance is exhausted")
    await require_current_work_caps(session, control, scope)
    if hold.day == day:
        return
    original.held_usd -= hold.amount_usd
    current.held_usd += hold.amount_usd
    await session.flush()
    hold.day = day


async def require_current_work_caps(
    session: AsyncSession, control: CompanyControl, scope: LedgerScope
) -> None:
    """Every fresh tool/model intent checks actual current own/ancestor spend.

    A truthful overbill or reduced allocation can invalidate an earlier hold.
    Recorded external charges remain intact; a cached authorization cannot
    permit another issued request merely because its day did not change.
    """
    task: UUID | None = scope.task_id
    seen: set[UUID] = set()
    for _ in range(16):
        if task is None:
            return
        registered = await session.get(RegisteredWork, (scope.company_id, task))
        total = await session.get(WorkBudget, (scope.company_id, task))
        if registered is None or task in seen or (task == scope.task_id and total is None):
            raise ValueError("Current work ancestry allowance is unavailable")
        seen.add(task)
        charged = total.held_usd + total.spent_usd if total else Decimal(0)
        if charged > min(
            control.work_cap_usd, registered.allocation_usd - registered.delegated_usd
        ):
            raise ValueError("Current work or ancestor allowance is exceeded")
        task = registered.parent_task_id
    raise ValueError("Current work ancestry exceeds the bounded directory lineage")
