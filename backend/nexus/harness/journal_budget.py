"""Transactional cost holds under the journal's per-company row lock."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import Capability, PrincipalAccess, VerifiedIdentity, require_capability
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.base import USD
from nexus.company.directory_models import (
    DirectoryCompany,
    DirectoryMembership,
    RegisteredWork,
    WorkPrincipal,
)
from nexus.company.directory_store import _lineage_active
from nexus.harness.journal_contracts import BudgetSnapshot, LedgerScope
from nexus.harness.journal_models import CompanyControl, CostHold, DailyBudget, WorkBudget

_MONEY = TypeAdapter(USD)


def billing_day(now: datetime) -> date:
    """Reject naive clocks and use the owner's Bangkok daily boundary."""
    if now.utcoffset() is None:
        raise ValueError("Billing clock must be timezone-aware")
    return now.astimezone(ZoneInfo("Asia/Bangkok")).date()


async def reserve_cost(
    session: AsyncSession,
    control: CompanyControl,
    action: ActionProposal,
    scope: LedgerScope,
    now: datetime,
) -> None:
    """Reserve both allowances in the caller's locked approval-consumption transaction."""
    await _reserve_cost(session, control, action, scope, now, control.work_cap_usd)


async def _reserve_cost(
    session: AsyncSession,
    control: CompanyControl,
    action: ActionProposal,
    scope: LedgerScope,
    now: datetime,
    work_cap_usd: Decimal,
) -> None:
    day = billing_day(now)
    daily, work = await budget_rows(session, scope, day)
    amount = action.estimated_cost_usd
    if daily.held_usd + daily.spent_usd + amount > control.daily_cap_usd:
        raise ValueError("Company daily allowance is exhausted")
    if work.held_usd + work.spent_usd + amount > work_cap_usd:
        raise ValueError("Logical work allowance is exhausted")
    daily.held_usd += amount
    work.held_usd += amount
    await session.flush()
    session.add(
        CostHold(
            action_id=action.action_id,
            company_id=scope.company_id,
            task_id=scope.task_id,
            day=day,
            amount_usd=amount,
            actual_usd=None,
            state="held",
        )
    )


async def reserve_registered_cost(
    session: AsyncSession,
    control: CompanyControl,
    action: ActionProposal,
    scope: LedgerScope,
    now: datetime,
) -> None:
    """Derive the own work cap from current locked state; no external cap override."""
    row = await session.scalar(
        select(RegisteredWork).where(
            RegisteredWork.company_id == scope.company_id,
            RegisteredWork.task_id == scope.task_id,
            RegisteredWork.trace_id == scope.trace_id,
            RegisteredWork.actor_id == scope.principal_id,
        )
    )
    if row is None or not row.active:
        raise ValueError("Registered work is absent or inactive")
    cap = _MONEY.validate_python(min(control.work_cap_usd, row.allocation_usd - row.delegated_usd))
    await _reserve_cost(session, control, action, scope, now, cap)


async def _member(
    session: AsyncSession, scope: LedgerScope, principal: UUID
) -> DirectoryMembership | None:
    member: DirectoryMembership | None = await session.scalar(
        select(DirectoryMembership).where(
            DirectoryMembership.company_id == scope.company_id,
            DirectoryMembership.principal_id == principal,
        )
    )
    return member


def _require_member(
    company: DirectoryCompany,
    member: DirectoryMembership | None,
    principal: UUID,
    capability: Capability,
) -> None:
    if member is None:
        raise ValueError("Current company membership is absent")
    access = PrincipalAccess.model_validate(
        {
            "company_id": company.company_id,
            "workspace_id": company.workspace_id,
            "principal_id": principal,
            "owner_id": company.owner_id,
            "membership_role": member.role,
            "company_active": company.company_active,
            "workspace_active": company.workspace_active,
            "principal_active": member.principal_active,
            "membership_active": member.membership_active,
        }
    )
    require_capability(access, capability)


async def require_registered_access(
    session: AsyncSession,
    control: CompanyControl,
    action: ActionProposal,
    scope: LedgerScope,
    identity: VerifiedIdentity,
    *,
    owner: bool,
) -> None:
    """Fresh same-transaction company/member/work validation under the first control lock."""
    if identity.principal_id != scope.principal_id:
        raise ValueError("Verified principal and work scope disagree")
    company = await session.get(DirectoryCompany, scope.company_id)
    if (
        company is None
        or company.workspace_id != identity.workspace_id
        or company.owner_id != control.owner_id
    ):
        raise ValueError("Current company/workspace/owner mapping disagrees")
    _require_member(
        company,
        await _member(session, scope, control.owner_id),
        control.owner_id,
        Capability.APPROVE,
    )
    _require_member(
        company,
        await _member(session, scope, scope.principal_id),
        scope.principal_id,
        Capability.APPROVE if owner else Capability.INTERNAL_PROPOSAL,
    )
    await _require_registered_work(session, company, action, scope, identity, owner=owner)


async def _require_registered_work(
    session: AsyncSession,
    company: DirectoryCompany,
    action: ActionProposal,
    scope: LedgerScope,
    identity: VerifiedIdentity,
    *,
    owner: bool,
) -> None:
    work = await session.scalar(
        select(RegisteredWork).where(
            RegisteredWork.company_id == scope.company_id,
            RegisteredWork.task_id == scope.task_id,
        )
    )
    if (
        work is None
        or (work.workspace_id, work.trace_id) != (identity.workspace_id, scope.trace_id)
        or (not owner and work.actor_id != scope.principal_id)
        or (action.company_id, action.task_id, action.trace_id, action.actor_id)
        != (work.company_id, work.task_id, work.trace_id, work.actor_id)
    ):
        raise ValueError("Registered immutable work identity or actor disagrees")
    _require_member(
        company,
        await _member(session, scope, work.actor_id),
        work.actor_id,
        Capability.INTERNAL_PROPOSAL,
    )
    grant = await session.scalar(
        select(WorkPrincipal).where(
            WorkPrincipal.company_id == scope.company_id,
            WorkPrincipal.task_id == work.task_id,
            WorkPrincipal.principal_id == work.actor_id,
        )
    )
    if grant is None or not await _lineage_active(session, work):
        raise ValueError("Registered actor grant or active ancestry is unavailable")


async def budget_rows(
    session: AsyncSession,
    scope: LedgerScope,
    day: date,
) -> tuple[DailyBudget, WorkBudget]:
    """Get or create persistent totals; the caller owns the company lock."""
    daily = await session.get(DailyBudget, (scope.company_id, day))
    work = await session.get(WorkBudget, (scope.company_id, scope.task_id))
    if daily is None:
        daily = DailyBudget(
            company_id=scope.company_id, day=day, held_usd=Decimal(0), spent_usd=Decimal(0)
        )
        session.add(daily)
    if work is None:
        work = WorkBudget(
            company_id=scope.company_id,
            task_id=scope.task_id,
            held_usd=Decimal(0),
            spent_usd=Decimal(0),
        )
        session.add(work)
    return daily, work


async def reconcile_cost(
    session: AsyncSession,
    scope: LedgerScope,
    action_id: UUID,
    actual_usd: Decimal | None,
) -> None:
    """Keep unknown billing reserved and record known real cost only once."""
    hold = await session.scalar(
        select(CostHold).where(
            CostHold.company_id == scope.company_id,
            CostHold.task_id == scope.task_id,
            CostHold.action_id == action_id,
        )
    )
    if hold is None:
        raise ValueError("Reservation is unavailable in this scope")
    actual = _MONEY.validate_python(actual_usd) if actual_usd is not None else None
    if hold.state == "reconciled":
        if actual is not None and hold.actual_usd != actual:
            raise ValueError("Conflicting reconciliation for a completed reservation")
        return
    if actual is None:
        hold.state = "unknown"
        return
    daily, work = await budget_rows(session, scope, hold.day)
    daily.held_usd -= hold.amount_usd
    work.held_usd -= hold.amount_usd
    daily.spent_usd += actual
    work.spent_usd += actual
    hold.actual_usd, hold.state = actual, "reconciled"


async def budget_snapshot(
    session: AsyncSession,
    control: CompanyControl,
    scope: LedgerScope,
    now: datetime,
) -> BudgetSnapshot:
    """Return day and lifetime-work amounts separately, including unresolved holds."""
    day = billing_day(now)
    daily, work = await budget_rows(session, scope, day)
    return BudgetSnapshot(
        company_id=scope.company_id,
        task_id=scope.task_id,
        day=day,
        daily_cap_usd=control.daily_cap_usd,
        daily_held_usd=daily.held_usd,
        daily_spent_usd=daily.spent_usd,
        work_cap_usd=control.work_cap_usd,
        work_held_usd=work.held_usd,
        work_spent_usd=work.spent_usd,
    )
