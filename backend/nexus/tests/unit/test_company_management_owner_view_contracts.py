"""Strict owner read boundaries preserve unknown money and reject unbounded page intent."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from nexus.company.management.owner_view_contracts import (
    CompanyBudget,
    DailyAllowance,
    OwnerViewPage,
)


@pytest.mark.parametrize("value", [True, "32", 101, 0])
def test_owner_page_requires_bounded_literal_limit(value: object) -> None:
    with pytest.raises(ValidationError):
        OwnerViewPage.model_validate({"limit": value})


def test_unknown_actual_total_is_distinct_from_known_subset_and_reserved_money() -> None:
    record = CompanyBudget(
        daily=DailyAllowance(
            day=date(2026, 10, 14),
            cap_usd=Decimal(5),
            held_usd=Decimal("0.03"),
            spent_usd=Decimal(0),
            available_usd=Decimal("4.97"),
        ),
        current_work_cap_usd=Decimal(1),
        root_lifetime_allocated_usd=Decimal(1),
        known_spent_usd=Decimal(0),
        reserved_any_day_usd=Decimal("0.03"),
        actual_total_usd=None,
        billing_unconfirmed=True,
    )
    reread = CompanyBudget.model_validate_json(record.model_dump_json())
    assert reread.actual_total_usd is None and reread.billing_unconfirmed
    assert reread.known_spent_usd == 0 and reread.reserved_any_day_usd == Decimal("0.03")
