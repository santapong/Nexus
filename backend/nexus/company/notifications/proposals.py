"""Exact native notification proposal declarations; no recipient/body authority from JSON."""

from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator

from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.base import SHA256, ValueContract, require_company
from nexus.company.notifications.contracts import NotificationContract

NOTIFICATION_TOOL = "company.owner-notification.send.v1"


class NotificationDispatchParameters(ValueContract):
    draft_id: UUID
    payload_sha256: SHA256
    recipient_policy_sha256: SHA256


class NotificationProposal(NotificationContract):
    """Owner recipient is resolved from the immutable draft, never action parameters."""

    draft_id: UUID
    payload_sha256: SHA256
    recipient_policy_sha256: SHA256
    action: ActionProposal
    transport: Literal["resend"] = "resend"

    @model_validator(mode="after")
    def exact_declared_action(self) -> Self:
        require_company(self.company_id, self.action)
        parameters = NotificationDispatchParameters(
            draft_id=self.draft_id,
            payload_sha256=self.payload_sha256,
            recipient_policy_sha256=self.recipient_policy_sha256,
        ).model_dump(mode="json")
        if self.action.tool != NOTIFICATION_TOOL or self.action.parameters != parameters:
            raise ValueError("Notification proposal differs from its exact native draft")
        return self
