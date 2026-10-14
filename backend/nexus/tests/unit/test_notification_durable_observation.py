"""Native descriptions conserve unknown and missing observations; no publication is inferred."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.delivery_contracts import SubmissionResult
from nexus.company.notifications.dispatch_contracts import NotificationProviderObservation
from nexus.execution.notification_worker_observation import notification_history_status


def receipt(outcome: str = "succeeded") -> ActionReceipt:
    return ActionReceipt.model_validate(
        {
            "company_id": UUID(int=1),
            "receipt_id": UUID(int=2),
            "action_id": UUID(int=3),
            "task_id": UUID(int=4),
            "trace_id": UUID(int=5),
            "proposal_hash": "a" * 64,
            "outcome": outcome,
            "recorded_at": datetime.now(UTC),
            "external_id": str(UUID(int=6)) if outcome == "succeeded" else None,
        }
    )


def observation(value: ActionReceipt, outcome: str) -> NotificationProviderObservation:
    return NotificationProviderObservation(
        company_id=value.company_id,
        observation_id=UUID(int=7),
        draft_id=UUID(int=8),
        action_id=value.action_id,
        payload_sha256="b" * 64,
        kind="submission",
        submission=SubmissionResult.model_validate(
            {
                "outcome": outcome,
                "reason": "accepted" if outcome == "accepted" else "provider_rejected",
                "provider_id": UUID(value.external_id)
                if outcome == "accepted" and value.external_id
                else None,
                "response_sha256": "c" * 64,
            }
        ),
        receipt_id=value.receipt_id,
        receipt_sha256=canonical_sha256(value),
        recorded_by=UUID(int=9),
        operation_id=value.action_id,
        audit_trace_id=value.trace_id,
        observed_at=value.recorded_at,
    )


def test_actual_success_description_keeps_missing_observation_missing() -> None:
    status, limitations = notification_history_status("succeeded", receipt(), None)
    assert status == "submitted" and "submission_observation_missing" in limitations


def test_failed_receipt_alone_is_not_a_proved_provider_rejection() -> None:
    status, limitations = notification_history_status("failed", receipt("failed"), None)
    assert status == "blocked" and "classification_unavailable" in limitations


@pytest.mark.parametrize("outcome,status", [("rejected", "rejected"), ("blocked", "blocked")])
def test_only_saved_original_submission_discriminates_failed_classification(
    outcome: str,
    status: str,
) -> None:
    value = receipt("failed")
    assert notification_history_status("failed", value, observation(value, outcome))[0] == status


@pytest.mark.parametrize("state", ["intent", "outcome_unknown"])
def test_issued_unknown_cannot_be_promoted_without_native_receipt(state: str) -> None:
    assert notification_history_status(state, None, None)[0] == "outcome_unknown"


def test_unknown_receipt_remains_unknown_even_with_compatible_saved_unknown_submission() -> None:
    value = receipt("outcome_unknown")
    assert (
        notification_history_status("outcome_unknown", value, observation(value, "unknown"))[0]
        == "outcome_unknown"
    )


def test_raw_submission_verdict_cannot_override_a_conflicting_actual_receipt() -> None:
    value = receipt("succeeded")
    with pytest.raises(ValueError):
        notification_history_status("succeeded", value, observation(value, "rejected"))


def test_known_native_terminal_state_without_a_receipt_is_corrupt() -> None:
    with pytest.raises(ValueError):
        notification_history_status("succeeded", None, None)
