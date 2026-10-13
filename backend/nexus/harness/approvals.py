"""Fail-closed approval checks; persistence supplies single-use enforcement."""

from __future__ import annotations

from uuid import UUID

from pydantic import AwareDatetime

from nexus.company.contracts.actions import ActionProposal, ApprovalDecision, ResourceRevision
from nexus.company.contracts.base import Contract, Name
from nexus.harness.canonical import action_hash


class ApprovalContext(Contract):
    """Authoritative current state supplied by a trusted authenticated runtime adapter.

    This contract is not an externally accepted authority token or an ACL lookup.
    """

    owner_id: UUID
    actor_id: UUID
    now: AwareDatetime
    policy_version: Name
    price_version: Name
    paused: bool
    resources: tuple[ResourceRevision, ...]


def require_exact_approval(
    action: ActionProposal,
    decision: ApprovalDecision,
    context: ApprovalContext,
) -> None:
    """Reject stale, changed, foreign, paused, future or unauthorized decisions."""
    company_ids = {action.company_id, decision.company_id, context.company_id}
    if len(company_ids) != 1 or context.paused:
        raise ValueError("Company scope mismatch or company is paused")
    if action.actor_id != context.actor_id or decision.approver_id != context.owner_id:
        raise ValueError("Actor or approver is not authorized")
    if decision.decision != "approved" or decision.action_id != action.action_id:
        raise ValueError("Approval is not for this action")
    if decision.action_revision != action.revision or decision.action_hash != action_hash(action):
        raise ValueError("Approval is not bound to this exact revision and payload")
    if not decision.issued_at <= context.now < decision.expires_at:
        raise ValueError("Approval is not currently valid")
    if (
        action.policy_version != context.policy_version
        or action.price_version != context.price_version
    ):
        raise ValueError("Policy or price version changed")
    current = {entry.resource: entry.revision for entry in context.resources}
    if len(current) != len(context.resources):
        raise ValueError("Current resource revisions are ambiguous")
    if any(current.get(entry.resource) != entry.revision for entry in action.preconditions):
        raise ValueError("Resource precondition changed or is unavailable")
