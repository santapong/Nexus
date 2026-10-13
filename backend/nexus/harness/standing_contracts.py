"""Exact owner-issued internal grants; tool eligibility belongs to server code."""

from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    field_validator,
    model_validator,
)

from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.base import USD, Contract, Name
from nexus.harness.approvals import ApprovalContext

_INTERNAL_TOOLS = MappingProxyType(
    {
        ("fake.internal.read.v1", "v1"): "internal_read",
        ("fake.internal.draft.v1", "v1"): "internal_draft",
    }
)


class StandingDeniedError(ValueError):
    """A current explicit grant does not authorize this exact internal action."""


class ToolPermission(BaseModel):
    """Exact tool/version/resource tuple, never a pattern or client risk declaration."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    tool: Name
    tool_version: Name
    resource: Name

    @field_validator("tool", "tool_version", "resource")
    @classmethod
    def forbid_patterns(cls, value: str) -> str:
        """Prevent wildcard grants even when an adapter might interpret glob syntax."""
        if any(symbol in value for symbol in "*?[]"):
            raise ValueError("Standing permissions must be exact identities")
        return value


class WorkAuthority(Contract):
    """Owner-declared current plan/charter binding; real M3 plan proof is separate."""

    task_id: UUID
    plan_id: UUID
    plan_revision: PositiveInt
    charter_id: UUID
    charter_revision: PositiveInt


class StandingGrant(WorkAuthority):
    """Immutable owner-approved capability snapshot for one actor and logical work."""

    grant_id: UUID
    actor_id: UUID
    owner_id: UUID
    policy_version: Name
    price_version: Name
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    permissions: tuple[ToolPermission, ...] = Field(min_length=1, max_length=100)
    max_action_cost_usd: USD

    @field_validator("max_action_cost_usd", mode="before")
    @classmethod
    def exact_cost(cls, value: object) -> object:
        """Refuse booleans and floats at the owner-issued monetary boundary."""
        if isinstance(value, (bool, float)):
            raise ValueError("Standing cost cap requires an exact decimal")
        return value

    @model_validator(mode="after")
    def bounded_snapshot(self) -> Self:
        """Require unique exact permissions and a positive pilot lifetime of at most 24h."""
        duration = (self.expires_at - self.issued_at).total_seconds()
        if not 0 < duration <= 86_400:
            raise ValueError("Standing lifetime must be positive and at most 24h")
        keys = [(p.tool, p.tool_version, p.resource) for p in self.permissions]
        if len(keys) != len(set(keys)):
            raise ValueError("Standing permissions must be unique")
        return self


class StandingRecord(Contract):
    """Immutable authority snapshot with separately persisted irreversible revocation."""

    grant: StandingGrant
    grant_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    active: bool
    revoked_at: AwareDatetime | None


def canonical_grant(grant: StandingGrant) -> str:
    """Normalize validated permission order and exact cost before persistent hashing."""
    snapshot = StandingGrant.model_validate_json(grant.model_dump_json())
    payload = snapshot.model_dump(mode="json")
    payload["permissions"] = sorted(
        payload["permissions"], key=lambda p: (p["tool"], p["tool_version"], p["resource"])
    )
    payload["max_action_cost_usd"] = format(snapshot.max_action_cost_usd, ".6f")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def grant_hash(grant: StandingGrant) -> str:
    """Bind the complete normalized grant, including owner, expiry and source revisions."""
    return hashlib.sha256(canonical_grant(grant).encode("utf-8")).hexdigest()


def require_eligible_permissions(grant: StandingGrant) -> None:
    """Only reviewed offline internal adapters are eligible; names grant no general trust."""
    if any((p.tool, p.tool_version) not in _INTERNAL_TOOLS for p in grant.permissions):
        raise StandingDeniedError("Standing grant contains an unregistered or external tool")


def require_binding_update(previous: WorkAuthority, current: WorkAuthority) -> None:
    """Permit exact replay or monotone owner binding revisions, never identity/counter reset."""
    if (previous.company_id, previous.task_id) != (current.company_id, current.task_id):
        raise StandingDeniedError("Work binding identity cannot change")
    for kind in ("plan", "charter"):
        before, after = getattr(previous, f"{kind}_revision"), getattr(current, f"{kind}_revision")
        if after < before or (
            getattr(previous, f"{kind}_id") != getattr(current, f"{kind}_id") and after <= before
        ):
            raise StandingDeniedError("Binding edits require monotone source revisions")


def require_standing_policy(
    grant: StandingGrant, action: ActionProposal, context: ApprovalContext, binding: WorkAuthority
) -> None:
    """Check an exact internal capability; persistence supplies activity and fresh identity."""
    require_eligible_permissions(grant)
    if (
        context.paused
        or {grant.company_id, action.company_id, context.company_id, binding.company_id}
        != {grant.company_id}
        or (grant.task_id, grant.actor_id, grant.owner_id)
        != (action.task_id, action.actor_id, context.owner_id)
        or action.actor_id != context.actor_id
        or not grant.issued_at <= context.now < grant.expires_at
    ):
        raise StandingDeniedError("Standing grant identity, lifetime or company state disagrees")
    if (grant.policy_version, grant.price_version) != (
        context.policy_version,
        context.price_version,
    ) or (action.policy_version, action.price_version) != (
        context.policy_version,
        context.price_version,
    ):
        raise StandingDeniedError("Standing grant uses stale policy or prices")
    expected = WorkAuthority.model_validate(
        {name: getattr(grant, name) for name in WorkAuthority.model_fields}
    )
    if expected != binding or action.estimated_cost_usd > grant.max_action_cost_usd:
        raise StandingDeniedError("Current plan/charter binding or action cost exceeds the grant")
    key = (action.tool, action.tool_version, action.resource)
    if key not in {(p.tool, p.tool_version, p.resource) for p in grant.permissions}:
        raise StandingDeniedError("Exact tool/version/resource is absent from the grant")
    current = {item.resource: item.revision for item in context.resources}
    if len(current) != len(context.resources) or any(
        current.get(item.resource) != item.revision for item in action.preconditions
    ):
        raise StandingDeniedError("Resource preconditions are stale, absent or ambiguous")
