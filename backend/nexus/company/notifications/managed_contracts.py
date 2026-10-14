"""Existing managed sender selectors and pending facts; declarations confer no permit."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BeforeValidator, model_validator

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import Flag, exact_count, exact_flag
from nexus.company.management.base import SHA256, ExactUSD, Name, ValueContract, require_company
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.plans import RunBinding
from nexus.company.notifications.contracts import NotificationContract
from nexus.harness.journal_contracts import ActionRecord


class NativeNotificationSelection(NotificationContract):
    draft_id: UUID
    sender_task_id: UUID
    plan: PlanRevisionRef

    @model_validator(mode="after")
    def exact_company(self) -> Self:
        require_company(self.company_id, self.plan)
        return self


class NotificationPreparationPolicy(ValueContract):
    """Trusted server configuration; no recipient/body/current-state flags from a selector."""

    enabled: Flag = False
    target: ResourceRef
    resource_symbol: Name
    workflow_name: Name = "internal.owner-notification"
    workflow_version: Name = "v1"
    estimated_cost_usd: ExactUSD = Decimal(".01")

    @model_validator(mode="after")
    def positive_estimate(self) -> Self:
        if self.estimated_cost_usd <= 0:
            raise ValueError("Managed notification needs a positive registered estimate")
        return self


class PreparedNotification(NotificationContract):
    """One actual pending/replayed journal record; no new scheduling/effect/model permission."""

    selection: NativeNotificationSelection
    sender: RunBinding
    registration_sha256: SHA256
    action: ActionRecord
    payload_sha256: SHA256
    recipient_policy_sha256: SHA256
    call_permit: Annotated[Literal[False], BeforeValidator(exact_flag)] = False
    scheduled: Annotated[Literal[False], BeforeValidator(exact_flag)] = False
    model_requests: Annotated[Literal[0], BeforeValidator(exact_count)] = 0

    @model_validator(mode="after")
    def actual_declared_binding(self) -> Self:
        require_company(self.company_id, self.selection, self.sender, self.action)
        action = self.action.proposal
        if (action.task_id, action.trace_id, action.actor_id) != (
            self.sender.task_id,
            self.sender.trace_id,
            self.sender.actor_id,
        ) or self.selection.sender_task_id != self.sender.task_id:
            raise ValueError("Prepared notification differs from its existing sender binding")
        return self
