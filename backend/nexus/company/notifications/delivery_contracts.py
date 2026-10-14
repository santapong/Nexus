"""Provider submission/delivery evidence is separate from authority and billing."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from nexus.company.management.base import SHA256, ValueContract
from nexus.company.notifications.contracts import NotificationContract

DeliveryState = Literal[
    "unknown",
    "delayed",
    "delivered",
    "bounced",
    "failed",
    "suppressed",
    "complained",
]
ProviderEvent = Literal[
    "bounced",
    "canceled",
    "clicked",
    "complained",
    "delivered",
    "delivery_delayed",
    "failed",
    "opened",
    "queued",
    "scheduled",
    "sent",
    "suppressed",
]
TransportReason = Literal[
    "accepted",
    "disabled",
    "configuration_missing",
    "recipient_policy",
    "invalid_key",
    "provider_rejected",
    "provider_conflict",
    "concurrent_unknown",
    "network_unknown",
    "provider_unknown",
    "invalid_response",
    "response_too_large",
    "lookup_unavailable",
    "content_mismatch",
    "observed",
]


class SubmissionResult(ValueContract):
    outcome: Literal["accepted", "rejected", "unknown", "blocked"]
    reason: TransportReason
    provider_id: UUID | None = None
    response_sha256: SHA256 | None = None
    delivery_state: Literal["unknown"] = "unknown"

    @model_validator(mode="after")
    def acceptance_identity(self) -> Self:
        if (self.outcome == "accepted") != (self.provider_id is not None):
            raise ValueError("Only an accepted provider response has an email identity")
        return self


class StatusResult(ValueContract):
    outcome: Literal["observed", "unavailable", "blocked"]
    reason: TransportReason
    provider_id: UUID
    provider_event: ProviderEvent | None = None
    response_sha256: SHA256 | None = None
    delivery_state: DeliveryState = "unknown"

    @model_validator(mode="after")
    def exact_observation(self) -> Self:
        if self.outcome == "observed" and (
            self.provider_event is None or self.response_sha256 is None
        ):
            raise ValueError("Observed delivery needs exact provider event/response evidence")
        if self.outcome != "observed" and (
            self.provider_event is not None or self.delivery_state != "unknown"
        ):
            raise ValueError("Unavailable lookup cannot assert a delivery state")
        return self


class DeliveryObservation(NotificationContract):
    """Immutable native publication envelope; caller JSON is not trusted provider evidence."""

    observation_id: UUID
    draft_id: UUID
    action_id: UUID
    provider_id: UUID
    payload_sha256: SHA256
    result: StatusResult
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def exact_provider(self) -> Self:
        if self.provider_id != self.result.provider_id:
            raise ValueError("Observation identifies another provider email")
        return self
