"""Owner budget projections distinguish daily limits from unconfirmed lifetime costs.

The SQL session is supplied: these are projection tests, not database isolation evidence.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import nexus.company.management.owner_view_budget as budget
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl, DailyBudget


@pytest.fixture
def control() -> CompanyControl:
    return CompanyControl(
        company_id=uuid4(),
        owner_id=uuid4(),
        policy_version="policy-v1",
        price_version="price-v1",
        daily_cap_usd=Decimal("5"),
        work_cap_usd=Decimal("1"),
        paused=False,
    )


def session_with_amounts(
    ledger: DailyBudget | None,
    *,
    allocated: Decimal | None,
    known: Decimal,
    reserved: Decimal,
    unconfirmed_count: int,
) -> MagicMock:
    """Use supplied aggregate rows while executing the real projection and SQL construction."""
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=ledger)
    session.scalar = AsyncMock(return_value=allocated)
    result = MagicMock()
    result.one.return_value = (known, reserved, unconfirmed_count)
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.parametrize("unconfirmed_count", [0, 1])
async def test_daily_projection_uses_bangkok_day_and_preserves_unconfirmed_cost(
    control: CompanyControl, monkeypatch: pytest.MonkeyPatch, unconfirmed_count: int
) -> None:
    # 17:30 UTC is already the next calendar day in Bangkok.
    monkeypatch.setattr(
        budget, "db_clock", AsyncMock(return_value=datetime(2026, 10, 29, 17, 30, tzinfo=UTC))
    )
    ledger = DailyBudget(held_usd=Decimal("1.25"), spent_usd=Decimal("2.50"))
    session = session_with_amounts(
        ledger,
        allocated=Decimal("3.00"),
        known=Decimal("2.50"),
        reserved=Decimal("1.75"),
        unconfirmed_count=unconfirmed_count,
    )
    projection = await budget.company_budget(cast(AsyncSession, session), control)

    session.get.assert_awaited_once_with(DailyBudget, (control.company_id, date(2026, 10, 30)))
    assert projection.daily.day == date(2026, 10, 30)
    assert projection.daily.available_usd == Decimal("1.25")
    assert projection.root_lifetime_allocated_usd == Decimal("3.00")
    assert projection.known_spent_usd == Decimal("2.50")
    assert projection.reserved_any_day_usd == Decimal("1.75")
    assert projection.billing_unconfirmed is bool(unconfirmed_count)
    assert projection.actual_total_usd == (None if unconfirmed_count else Decimal("2.50"))


@pytest.mark.parametrize("held,spent", [("0", "0"), ("3", "2"), ("4", "2")])
async def test_daily_available_never_goes_below_zero(
    control: CompanyControl, monkeypatch: pytest.MonkeyPatch, held: str, spent: str
) -> None:
    monkeypatch.setattr(
        budget, "db_clock", AsyncMock(return_value=datetime(2026, 10, 29, tzinfo=UTC))
    )
    ledger = DailyBudget(held_usd=Decimal(held), spent_usd=Decimal(spent))
    session = session_with_amounts(
        ledger, allocated=Decimal(0), known=Decimal(0), reserved=Decimal(0), unconfirmed_count=0
    )
    projection = await budget.company_budget(cast(AsyncSession, session), control)
    assert projection.daily.available_usd == max(
        Decimal(0), Decimal(5) - Decimal(held) - Decimal(spent)
    )


async def test_missing_daily_ledger_is_zero_but_missing_root_aggregate_is_denied(
    control: CompanyControl, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        budget, "db_clock", AsyncMock(return_value=datetime(2026, 10, 29, tzinfo=UTC))
    )
    session = session_with_amounts(
        None, allocated=Decimal(0), known=Decimal(0), reserved=Decimal(0), unconfirmed_count=0
    )
    projection = await budget.company_budget(cast(AsyncSession, session), control)
    assert projection.daily.held_usd == projection.daily.spent_usd == Decimal(0)
    assert projection.daily.available_usd == Decimal(5)
    session.scalar.return_value = None
    with pytest.raises(ManagementDeniedError, match="aggregate is unavailable"):
        await budget.company_budget(cast(AsyncSession, session), control)


async def test_cross_company_work_cannot_read_costs(control: CompanyControl) -> None:
    session = session_with_amounts(
        None, allocated=Decimal(0), known=Decimal(0), reserved=Decimal(0), unconfirmed_count=0
    )
    work = ExecutionWork(company_id=uuid4(), task_id=uuid4())
    with pytest.raises(ManagementDeniedError, match="company differs"):
        await budget.actual_amounts(cast(AsyncSession, session), control, work)
    session.execute.assert_not_awaited()


async def test_work_cost_query_is_company_and_task_scoped(control: CompanyControl) -> None:
    task_id = uuid4()
    work = ExecutionWork(company_id=control.company_id, task_id=task_id)
    session = session_with_amounts(
        None,
        allocated=Decimal(0),
        known=Decimal("0.1"),
        reserved=Decimal("0.2"),
        unconfirmed_count=1,
    )
    amounts = await budget.actual_amounts(cast(AsyncSession, session), control, work)
    statement = session.execute.await_args.args[0]
    compiled = statement.compile()
    params = tuple(compiled.params.values())
    assert control.company_id in params and task_id in params
    assert "company_cost_holds.company_id" in str(compiled)
    assert "company_cost_holds.task_id" in str(compiled)
    assert "company_effect_intents" in str(compiled)
    assert amounts == budget.ActualAmounts(Decimal("0.1"), Decimal("0.2"), True)
