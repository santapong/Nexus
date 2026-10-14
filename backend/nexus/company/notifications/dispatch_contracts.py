"""Strict recorded provider evidence; decoding it is neither a permit nor approval."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from nexus.company.management.base import SHA256
from nexus.company.notifications.contracts import NotificationContract
from nexus.company.notifications.delivery_contracts import StatusResult, SubmissionResult


class NotificationProviderObservation(NotificationContract):
    observation_id: UUID
    draft_id: UUID
    action_id: UUID
    payload_sha256: SHA256
    kind: Literal["submission", "delivery", "reconciliation"]
    submission: SubmissionResult | None = None
    status: StatusResult | None = None
    receipt_id: UUID
    receipt_sha256: SHA256
    recorded_by: UUID
    operation_id: UUID
    audit_trace_id: UUID
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def exact_result_kind(self) -> Self:
        if (self.kind == "delivery") != (self.status is not None) or (self.kind != "delivery") != (
            self.submission is not None
        ):
            raise ValueError("Provider evidence must identify one exact result kind")
        return self
