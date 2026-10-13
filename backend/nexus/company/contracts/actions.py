"""Exact consequential action and single-use approval wire contracts."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PositiveInt,
    field_serializer,
    field_validator,
    model_validator,
)

from nexus.company.contracts.base import USD, Contract, Name


class ResourceRevision(BaseModel):
    """An opaque resource identity and its expected revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    resource: Name
    revision: Name


class ActionProposal(Contract):
    """Exact actor, tool, resource, cost and preconditions requiring authorization."""

    canonicalization: Literal["nexus-action-v1"] = "nexus-action-v1"
    action_id: UUID
    task_id: UUID
    trace_id: UUID
    actor_id: UUID
    revision: PositiveInt
    tool: Name
    tool_version: Name
    resource: Name
    parameters: dict[str, JsonValue]
    preconditions: tuple[ResourceRevision, ...] = ()
    policy_version: Name
    price_version: Name
    estimated_cost_usd: USD

    @field_validator("parameters")
    @classmethod
    def finite_json(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Forbid non-standard JSON values before hashing or storage."""
        json.dumps(value, allow_nan=False)
        return value

    @field_serializer("estimated_cost_usd")
    def stable_cost(self, value: Decimal) -> str:
        """Represent equivalent monetary values identically on the wire."""
        return format(value.quantize(Decimal("0.000001")), "f")

    @model_validator(mode="after")
    def unique_preconditions(self) -> Self:
        """Prevent conflicting revisions of the same resource in one action."""
        if len({entry.resource for entry in self.preconditions}) != len(self.preconditions):
            raise ValueError("Resource preconditions must be unique")
        return self


class ApprovalDecision(Contract):
    """Owner decision for one exact proposal, with a finite aware-time validity window."""

    decision_id: UUID
    action_id: UUID
    action_revision: PositiveInt
    action_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approver_id: UUID
    decision: Literal["approved", "rejected"]
    issued_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def finite_window(self) -> Self:
        """Disallow an empty, reversed or greater-than-24-hour approval window."""
        duration = (self.expires_at - self.issued_at).total_seconds()
        if not 0 < duration <= 86_400:
            raise ValueError("Approval validity must be greater than zero and at most 24 hours")
        return self
