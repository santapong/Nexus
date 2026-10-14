"""Native selectors and canonical digest timing reject caller semantic/clock/hash claims."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.native_fact_contracts import (
    CapSelector,
    CompanyCapState,
    FailedReceiptSelector,
    NativeEventSelector,
    NativeFactProjection,
)
from nexus.company.brain.native_fact_digest import digest_window
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.canonical import canonical_json, canonical_sha256


@pytest.mark.parametrize(
    "kind", ["decision_required", "work_blocked", "cap_exhausted", "digest_due", "receipt_recorded"]
)
def test_selectors_never_accept_caller_state_amount_hash_or_due_time(kind: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(NativeEventSelector).validate_python(
            {
                "company_id": UUID(int=1),
                "kind": kind,
                "state_sha256": "a" * 64,
                "amount": "0.0",
                "now": datetime.now(UTC),
            }
        )


@pytest.mark.parametrize(
    ("kind", "now", "expected"),
    [
        ("daily", "2026-10-14T01:59:59+00:00", None),
        ("daily", "2026-10-14T02:00:00+00:00", "daily:2026-10-14"),
        ("weekly", "2026-10-12T01:59:59+00:00", None),
        ("weekly", "2026-10-14T02:00:00+00:00", "weekly:2026-10-12"),
        ("daily", "2026-10-14T17:00:00+00:00", None),
    ],
)
def test_digest_canonical_bangkok_windows(kind: str, now: str, expected: str | None) -> None:
    result = digest_window(kind, datetime.fromisoformat(now))
    assert (result[0] if result else None) == expected
    if result:
        offset = result[1].utcoffset()
        assert result[1].hour == 9 and offset is not None and offset.total_seconds() == 25200


def test_company_cap_canonical_state_keeps_exact_sql_day_and_unknown_billing() -> None:
    state = CompanyCapState.model_validate(
        {
            "company_id": UUID(int=1),
            "budget_day": date(2026, 10, 14),
            "cap_usd": Decimal("5.000000"),
            "held_usd": Decimal("5.000000"),
            "spent_usd": Decimal("0.000000"),
            "billing_unknown": False,
            "policy_version": "actual-v1",
        }
    )
    assert '"budget_day":"2026-10-14"' in canonical_json(state)
    assert canonical_sha256(state) == canonical_sha256(
        CompanyCapState.model_validate_json(state.model_dump_json())
    )
    assert canonical_sha256(state) != canonical_sha256(
        state.model_copy(update={"budget_day": date(2026, 10, 15)})
    )
    assert canonical_sha256(state) != canonical_sha256(
        state.model_copy(update={"billing_unknown": True})
    )
    fact = NativeFactProjection(
        company_id=state.company_id,
        selector=CapSelector(company_id=state.company_id),
        state=state,
        resource=ResourceRef(company_id=state.company_id, resource_id=UUID(int=2)),
        required_resource_ids=(UUID(int=2),),
        source_recorded_at=datetime.now(UTC),
    )
    assert fact.source_event.precision == "day" and fact.source_event.value == "2026-10-14"


def test_receipt_source_date_comes_from_exact_native_state_not_redundant_observation() -> None:
    stamp = datetime.fromisoformat("2026-10-14T12:34:56+07:00")
    receipt = ActionReceipt(
        company_id=UUID(int=1),
        receipt_id=UUID(int=2),
        action_id=UUID(int=3),
        task_id=UUID(int=4),
        trace_id=UUID(int=5),
        proposal_hash="c" * 64,
        outcome="failed",
        recorded_at=stamp,
    )
    fact = NativeFactProjection(
        company_id=receipt.company_id,
        selector=FailedReceiptSelector(company_id=receipt.company_id, action_id=receipt.action_id),
        state=receipt,
        resource=ResourceRef(company_id=receipt.company_id, resource_id=UUID(int=6)),
        required_resource_ids=(UUID(int=6),),
        source_recorded_at=datetime.now(UTC),
    )
    assert fact.source_event.precision == "instant" and fact.source_event.value == stamp.isoformat()
