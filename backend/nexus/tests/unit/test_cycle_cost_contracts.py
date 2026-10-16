"""Financial projections describe supplied native data, never family or work acceptance."""

from decimal import Decimal
from uuid import UUID

import pytest

from nexus.company.management.cycle_cost_contracts import (
    FamilyCharge,
    family_charge_totals,
)


def charge(*, unknown: bool = False) -> FamilyCharge:
    return FamilyCharge(
        action_id=UUID(int=1),
        task_id=UUID(int=2),
        attempt_kind="tool_attempts",
        native_state="outcome_unknown" if unknown else "failed",
        hold_state="unknown" if unknown else "reconciled",
        reserved_usd=Decimal(".2"),
        ledger_actual_usd=None if unknown else Decimal(".1"),
        receipt_id=None if unknown else UUID(int=3),
        confirmation="unconfirmed" if unknown else "known",
        blockers=("outcome_unknown",) if unknown else (),
    )


def test_known_failed_charge_and_exact_replay_are_counted_once() -> None:
    value = charge()
    result = family_charge_totals((value, value))
    assert result.known_spent_usd == Decimal(".1") and result.held_usd == 0
    assert result.actual_total_usd == Decimal(".1") and result.action_count == 1


def test_unknown_and_missing_holds_are_never_fabricated_free() -> None:
    value = charge(unknown=True)
    result = family_charge_totals((value,))
    assert result.known_spent_usd == 0 and result.held_usd == Decimal(".2")
    assert result.actual_total_usd is None and result.unconfirmed_action_ids == (value.action_id,)
    missing = value.model_copy(update={"hold_state": None, "reserved_usd": None})
    assert family_charge_totals((missing,)).held_usd is None


def test_conflicting_duplicate_or_forged_confirmation_is_denied() -> None:
    original = charge()
    with pytest.raises(ValueError):
        family_charge_totals(
            (original, original.model_copy(update={"ledger_actual_usd": Decimal(".3")}))
        )
    with pytest.raises(ValueError):
        family_charge_totals((charge(unknown=True).model_copy(update={"confirmation": "known"}),))
