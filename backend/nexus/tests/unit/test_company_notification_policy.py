"""Declared server projections are fixtures, never native issuance authority."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.notifications.contracts import (
    NativeNotificationSignal,
    NotificationPolicy,
)
from nexus.company.notifications.policy import (
    digest_bucket,
    routine_admission,
    signal_admission,
    trigger_sha256,
)
from nexus.company.notifications.usage_rules import RoutineIntentFact

NOW = datetime(2035, 2, 5, 2, tzinfo=UTC)  # Monday09:00Bangkok.
COMPANY = UUID(int=1)


def signal(kind: str = "decision_required") -> NativeNotificationSignal:
    return NativeNotificationSignal.model_validate(
        {
            "company_id": COMPANY,
            "event_ids": (UUID(int=10),),
            "subject_id": UUID(int=20),
            "kind": kind,
            "state_sha256": "a" * 64,
            "source_event": {"precision": "unknown", "value": None, "basis": "fixture"},
            "observed_at": NOW,
        }
    )


def test_disabled_and_idle_never_issue() -> None:
    assert signal_admission(NotificationPolicy(), signal()).reason == "disabled"
    active = NotificationPolicy(enabled=True)
    for kind in ("idle", "candidate", "metric_satisfied", "unchanged"):
        assert signal_admission(active, signal(kind)).state == "suppressed"


@pytest.mark.parametrize("kind", ["decision_required", "blocked", "failed", "cap_exhausted"])
def test_meaningful_changed_native_projection(kind: str) -> None:
    assert signal_admission(NotificationPolicy(enabled=True), signal(kind)).state == "eligible"


def test_completion_without_current_exact_independent_proof_is_blocked() -> None:
    assert (
        signal_admission(NotificationPolicy(enabled=True), signal("work_accepted")).reason
        == "acceptance_unavailable"
    )


def test_state_dedup_ignores_event_and_clock_but_not_actual_state() -> None:
    first = signal()
    second = first.model_copy(
        update={"event_ids": (UUID(int=11),), "observed_at": NOW + timedelta(days=2)}
    )
    assert trigger_sha256(first) == trigger_sha256(second)
    changed = first.model_copy(update={"state_sha256": "b" * 64})
    assert trigger_sha256(first) != trigger_sha256(changed)
    assert (
        signal_admission(
            NotificationPolicy(enabled=True), second, existing_trigger_sha256=trigger_sha256(first)
        ).reason
        == "coalesced"
    )


def test_digest_requires_explicit_registered_schedule() -> None:
    assert digest_bucket(NotificationPolicy(enabled=True), NOW, "daily") is None
    active = NotificationPolicy(enabled=True, daily_digest=True, weekly_digest=True)
    assert digest_bucket(active, NOW, "daily") == "daily:2035-02-05"
    assert digest_bucket(active, NOW, "weekly") == "weekly:2035-02-05"
    assert digest_bucket(active, NOW + timedelta(minutes=1), "daily") is None
    assert digest_bucket(active, NOW + timedelta(days=1), "weekly") is None


def intent(index: int = 0) -> RoutineIntentFact:
    return RoutineIntentFact(
        company_id=COMPANY,
        action_id=UUID(int=100 + index),
        draft_id=UUID(int=200 + index),
        payload_sha256="a" * 64,
        kind="routine",
        issued_at=NOW,
    )


def test_day_slots_include_unknown_attempts_and_never_reset_at_provider_retention() -> None:
    policy = NotificationPolicy(enabled=True)
    issued = tuple(intent(index) for index in range(10))
    assert routine_admission(policy, COMPANY, NOW, issued[:9]).state == "eligible"
    assert routine_admission(policy, COMPANY, NOW, issued).reason == "daily_cap"
    old = tuple(item.model_copy(update={"issued_at": NOW - timedelta(days=1)}) for item in issued)
    assert routine_admission(policy, COMPANY, NOW, old).state == "eligible"
    future = (issued[0].model_copy(update={"issued_at": NOW + timedelta(seconds=1)}),)
    assert routine_admission(policy, COMPANY, NOW, future).reason == "invalid_snapshot"


def test_duplicate_intent_projections_count_once_and_conflicting_duplicates_deny() -> None:
    policy = NotificationPolicy(enabled=True)
    item = intent()
    assert routine_admission(policy, COMPANY, NOW, (item, item)).routine_slots_used == 1
    for changed in (
        item.model_copy(update={"payload_sha256": "b" * 64}),
        item.model_copy(update={"action_id": UUID(int=101)}),
        item.model_copy(update={"company_id": UUID(int=99)}),
    ):
        assert routine_admission(policy, COMPANY, NOW, (item, changed)).reason == "invalid_snapshot"
    digest = item.model_copy(update={"kind": "daily"})
    assert routine_admission(policy, COMPANY, NOW, (digest,)).routine_slots_used == 0


@pytest.mark.parametrize("value", [True, 1.0, "1", 0, 11])
def test_cap_has_literal_bounded_integer(value: object) -> None:
    with pytest.raises(ValidationError):
        NotificationPolicy.model_validate({"routine_per_day": value})
