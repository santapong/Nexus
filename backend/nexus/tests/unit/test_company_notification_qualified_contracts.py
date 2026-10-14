"""Old routine wire/canonical bytes are exact; new optional metadata never creates authority."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.management.canonical import canonical_json, canonical_sha256
from nexus.company.notifications.contracts import (
    NativeDigestBinding,
    NativeNotificationSignal,
    NotificationContract,
    NotificationDraft,
    NotificationPolicy,
)
from nexus.company.notifications.notification_base import NotificationContract as ExtractedBase
from nexus.company.notifications.policy import signal_admission, trigger_sha256
from nexus.company.notifications.signal_contracts import NativeNotificationSignal as ExtractedSignal


@pytest.mark.parametrize("index", [0, 1])
def test_pre015_routine_wire_and_canonical_hash_stay_exact(index: int) -> None:
    path = (
        Path(__file__).resolve().parents[1] / "fixtures/native-notification-routine-before015.json"
    )
    frozen = json.loads(path.read_text())[index]
    draft = NotificationDraft.model_validate_json(frozen["json"])
    assert draft.model_dump_json(by_alias=True) == frozen["json"]
    assert canonical_json(draft) == frozen["canonical_json"]
    assert canonical_sha256(draft) == frozen["canonical_sha256"]
    assert trigger_sha256(draft.signal) == frozen["trigger_sha256"]


@pytest.mark.parametrize("change", ["bucket", "hour", "weekly_day", "hash", "authority"])
def test_digest_binding_rejects_wrong_native_shape_or_authority_field(change: str) -> None:
    value = {
        "company_id": UUID(int=1),
        "report_id": UUID(int=2),
        "report_snapshot_sha256": "a" * 64,
        "registration_sha256": "b" * 64,
        "policy_sha256": "c" * 64,
        "kind": "daily",
        "due_bucket": "daily:2026-10-14",
        "scheduled_for": datetime(2026, 10, 14, 2, tzinfo=UTC),
    }
    if change == "bucket":
        value["due_bucket"] = "daily:2026-10-15"
    elif change == "hour":
        value["scheduled_for"] = datetime(2026, 10, 14, 3, tzinfo=UTC)
    elif change == "weekly_day":
        value.update(kind="weekly", due_bucket="weekly:2026-10-14")
    elif change == "hash":
        value["registration_sha256"] = "short"
    else:
        value["approved"] = True
    with pytest.raises(ValidationError):
        NativeDigestBinding.model_validate(value)


def test_budget_day_and_digest_are_explicit_kind_subject_bindings() -> None:
    frozen = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "fixtures/native-notification-routine-before015.json"
        ).read_text()
    )[0]
    signal = NotificationDraft.model_validate_json(frozen["json"]).signal
    with pytest.raises(ValidationError):
        NativeNotificationSignal.model_validate(
            signal.model_dump() | {"budget_day": date(2026, 10, 14)}
        )
    with pytest.raises(ValidationError):
        NativeNotificationSignal.model_validate(signal.model_dump() | {"kind": "digest_due"})


def test_compatibility_reexports_retain_single_public_class_identity() -> None:
    assert ExtractedBase is NotificationContract and ExtractedSignal is NativeNotificationSignal
    assert (
        NotificationContract.__module__
        == NativeNotificationSignal.__module__
        == "nexus.company.notifications.contracts"
    )


def test_digest_draft_has_exact_kind_policy_bucket_and_roundtrips() -> None:
    frozen = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "fixtures/native-notification-routine-before015.json"
        ).read_text()
    )[0]
    old = NotificationDraft.model_validate_json(frozen["json"])
    policy = NotificationPolicy(enabled=True, daily_digest=True)
    binding = NativeDigestBinding(
        company_id=old.company_id,
        report_id=UUID(int=100),
        report_snapshot_sha256="a" * 64,
        registration_sha256="b" * 64,
        policy_sha256=canonical_sha256(policy),
        kind="daily",
        due_bucket="daily:2026-10-14",
        scheduled_for=datetime(2026, 10, 14, 2, tzinfo=UTC),
    )
    signal = NativeNotificationSignal.model_validate(
        old.signal.model_dump()
        | {"kind": "digest_due", "subject_id": binding.report_id, "digest": binding}
    )
    values = old.model_dump() | {
        "signal": signal,
        "trigger_sha256": trigger_sha256(signal),
        "kind": "daily",
        "due_bucket": binding.due_bucket,
        "scheduled_for": binding.scheduled_for,
    }
    draft = NotificationDraft.model_validate(values)
    assert NotificationDraft.model_validate_json(draft.model_dump_json()) == draft
    assert signal_admission(policy, signal).state == "eligible"
    assert (
        signal_admission(policy.model_copy(update={"daily_digest": False}), signal).state
        == "blocked"
    )
    for override in (
        {"kind": "routine"},
        {"kind": "weekly"},
        {"due_bucket": "daily:2026-10-15"},
        {"scheduled_for": None},
    ):
        with pytest.raises(ValidationError):
            NotificationDraft.model_validate(values | override)


def test_company_budget_day_preserves_exact_native_date_in_python_canonical_payload() -> None:
    frozen = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "fixtures/native-notification-routine-before015.json"
        ).read_text()
    )[0]
    old = NotificationDraft.model_validate_json(frozen["json"])
    signal = NativeNotificationSignal.model_validate(
        old.signal.model_dump()
        | {"kind": "cap_exhausted", "subject_id": old.company_id, "budget_day": date(2026, 10, 14)}
    )
    assert '"budget_day":"2026-10-14"' in canonical_json(signal)
    assert NativeNotificationSignal.model_validate_json(signal.model_dump_json()) == signal
