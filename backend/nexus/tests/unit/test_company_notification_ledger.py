"""Pure immutable replay/delivery declarations; no DB or external permit proof."""

from datetime import timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.management.plans import RunBinding
from nexus.company.notifications.contracts import NotificationAttempt
from nexus.company.notifications.delivery_contracts import (
    DeliveryObservation,
    StatusResult,
    SubmissionResult,
)
from nexus.company.notifications.ledger_rules import (
    NotificationConflictError,
    delivery_projection,
    dispatch_disposition,
    require_exact_replay,
    stable_idempotency_key,
)
from nexus.tests.notification_rule_fixtures import COMPANY, NOW, OWNER, WORKSPACE, declared_draft


def declared_attempt() -> NotificationAttempt:
    draft = declared_draft()
    return NotificationAttempt(
        company_id=COMPANY,
        draft_id=draft.draft_id,
        action_id=UUID(int=40),
        work=RunBinding(
            company_id=COMPANY,
            workspace_id=WORKSPACE,
            actor_id=OWNER,
            task_id=UUID(int=20),
            trace_id=UUID(int=21),
            run_id=UUID(int=22),
            workflow_name="notification",
            workflow_version="notification.v1",
            model_profile="offline-none",
            model_registry_version="offline-none.v1",
        ),
        proposal_sha256="c" * 64,
        payload_sha256=draft.payload_sha256,
        recipient_policy_sha256=draft.recipient_policy.sha256,
        intent_fence=1,
        idempotency_key=stable_idempotency_key(COMPANY, draft.draft_id),
        kind="routine",
        bangkok_day=NOW.date(),
        issued_at=NOW,
    )


def observation(event: str, *, offset: int = 0) -> DeliveryObservation:
    states = {"delivered": "delivered", "bounced": "bounced", "opened": "unknown"}
    return DeliveryObservation.model_validate(
        {
            "company_id": COMPANY,
            "observation_id": UUID(int=60 + offset),
            "draft_id": UUID(int=30),
            "action_id": UUID(int=40),
            "provider_id": UUID(int=100),
            "payload_sha256": declared_draft().payload_sha256,
            "observed_at": NOW + timedelta(seconds=offset),
            "result": {
                "outcome": "observed",
                "reason": "observed",
                "provider_id": UUID(int=100),
                "provider_event": event,
                "delivery_state": states[event],
                "response_sha256": "f" * 64,
            },
        }
    )


def test_permanent_intent_replay_never_regains_send_after_24h() -> None:
    draft = declared_draft()
    attempt = declared_attempt()
    require_exact_replay(draft, draft)
    assert dispatch_disposition(draft, None).state == "unissued"
    assert dispatch_disposition(draft, attempt).state == "reconcile"
    old = attempt.model_copy(update={"issued_at": NOW - timedelta(days=30)})
    assert dispatch_disposition(draft, old).state == "reconcile"
    changed = attempt.model_copy(update={"payload_sha256": "e" * 64})
    assert dispatch_disposition(draft, changed).state == "conflict"
    with pytest.raises(NotificationConflictError):
        require_exact_replay(draft, draft.model_copy(update={"audit_trace_id": UUID(int=900)}))


@pytest.mark.parametrize(
    "change",
    [
        {"idempotency_key": "rotated-provider-key"},
        {"attempt_number": True},
        {"bangkok_day": NOW.date() - timedelta(days=1)},
    ],
)
def test_attempt_binding_rejects_rotated_key_fake_integer_or_wrong_day(
    change: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        NotificationAttempt.model_validate(declared_attempt().model_dump() | change)


def test_acceptance_and_failed_lookup_do_not_erase_known_delivery_or_invent_it() -> None:
    submitted = SubmissionResult(outcome="accepted", reason="accepted", provider_id=UUID(int=100))
    assert delivery_projection(submitted, ()).delivery_state == "unknown"
    unavailable = observation("delivered", offset=2).model_copy(
        update={
            "result": StatusResult(
                outcome="unavailable", reason="lookup_unavailable", provider_id=UUID(int=100)
            )
        }
    )
    projected = delivery_projection(
        submitted, (observation("delivered"), observation("opened", offset=1), unavailable)
    )
    assert projected.delivery_state == "delivered" and projected.lookup_state == "unavailable"
    unknown = SubmissionResult(outcome="unknown", reason="network_unknown")
    assert delivery_projection(unknown, ()).delivery_state == "unknown"


def test_delivery_history_rejects_cross_draft_provider_or_reverse_time() -> None:
    submitted = SubmissionResult(outcome="accepted", reason="accepted", provider_id=UUID(int=100))
    first = observation("delivered")
    for changed in (
        observation("bounced", offset=1).model_copy(update={"draft_id": UUID(int=900)}),
        observation("bounced", offset=1).model_copy(update={"provider_id": UUID(int=900)}),
        observation("bounced", offset=1).model_copy(
            update={"observed_at": NOW - timedelta(seconds=1)}
        ),
    ):
        with pytest.raises(NotificationConflictError):
            delivery_projection(submitted, (first, changed))
