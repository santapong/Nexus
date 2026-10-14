"""Permanent dedup/projection descriptions; caller values never authorize ledger writes."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime

from nexus.company.management.base import ValueContract
from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.contracts import NotificationAttempt, NotificationDraft
from nexus.company.notifications.delivery_contracts import (
    DeliveryObservation,
    DeliveryState,
    SubmissionResult,
)


class NotificationConflictError(ValueError):
    """Immutable notification identity was reused with different native content."""


class DispatchDisposition(ValueContract):
    state: Literal["unissued", "reconcile", "conflict"]


class DeliveryProjection(ValueContract):
    submission_outcome: Literal["accepted", "rejected", "unknown", "blocked"]
    provider_id: UUID | None
    delivery_state: DeliveryState
    lookup_state: Literal["not_observed", "observed", "unavailable"]
    last_observed_at: AwareDatetime | None = None


def stable_idempotency_key(company_id: UUID, draft_id: UUID) -> str:
    """Local permanent draft identity; never rotate after provider-key expiry."""
    return f"nexus-owner-{company_id.hex}-{draft_id.hex}"


def require_exact_replay(existing: NotificationDraft, requested: NotificationDraft) -> None:
    if canonical_sha256(existing) != canonical_sha256(requested):
        raise NotificationConflictError("Notification replay differs from immutable native draft")


def dispatch_disposition(
    draft: NotificationDraft, previous: NotificationAttempt | None
) -> DispatchDisposition:
    """Any existing intent requires reconciliation, regardless of time or provider ID."""
    if previous is None:
        return DispatchDisposition(state="unissued")
    exact = (
        previous.company_id == draft.company_id
        and previous.draft_id == draft.draft_id
        and previous.payload_sha256 == draft.payload_sha256
        and previous.recipient_policy_sha256 == draft.recipient_policy.sha256
        and previous.idempotency_key == stable_idempotency_key(draft.company_id, draft.draft_id)
    )
    return DispatchDisposition(state="reconcile" if exact else "conflict")


def delivery_projection(
    submission: SubmissionResult,
    observations: tuple[DeliveryObservation, ...],
) -> DeliveryProjection:
    if len(observations) > 1000:
        raise NotificationConflictError("Notification observation window exceeds its bound")
    state: DeliveryState = "unknown"
    last_time: datetime | None = None
    lookup: Literal["not_observed", "observed", "unavailable"] = "not_observed"
    binding: tuple[UUID, UUID, UUID, str] | None = None
    for observation in observations:
        current = (
            observation.company_id,
            observation.draft_id,
            observation.action_id,
            observation.payload_sha256,
        )
        if (
            observation.provider_id != submission.provider_id
            or (binding is not None and current != binding)
            or (last_time is not None and observation.observed_at < last_time)
        ):
            raise NotificationConflictError(
                "Delivery observations differ from exact native binding"
            )
        binding, last_time = current, observation.observed_at
        lookup = "observed" if observation.result.outcome == "observed" else "unavailable"
        if (
            observation.result.outcome == "observed"
            and observation.result.delivery_state != "unknown"
        ):
            state = observation.result.delivery_state
    return DeliveryProjection(
        submission_outcome=submission.outcome,
        provider_id=submission.provider_id,
        delivery_state=state,
        lookup_state=lookup,
        last_observed_at=last_time,
    )
