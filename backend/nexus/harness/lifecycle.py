"""Explicit action transitions with uncertain effects and fail-closed completion."""

from __future__ import annotations

from enum import StrEnum


class ActionState(StrEnum):
    """Persisted consequential-action lifecycle, separate from work/verification status."""

    PROPOSED = "proposed"
    VALIDATED = "validated"
    AWAITING_APPROVAL = "awaiting_approval"
    AUTHORIZED = "authorized"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"
    OUTCOME_UNKNOWN = "outcome_unknown"


_TRANSITIONS: dict[ActionState, frozenset[ActionState]] = {
    ActionState.PROPOSED: frozenset(
        {ActionState.VALIDATED, ActionState.REJECTED, ActionState.CANCELLED}
    ),
    ActionState.VALIDATED: frozenset(
        {
            ActionState.AWAITING_APPROVAL,
            ActionState.AUTHORIZED,
            ActionState.FAILED,
            ActionState.CANCELLED,
        }
    ),
    ActionState.AWAITING_APPROVAL: frozenset(
        {ActionState.AUTHORIZED, ActionState.REJECTED, ActionState.EXPIRED, ActionState.CANCELLED}
    ),
    ActionState.AUTHORIZED: frozenset(
        {ActionState.EXECUTING, ActionState.CANCELLED, ActionState.EXPIRED}
    ),
    ActionState.EXECUTING: frozenset(
        {ActionState.VERIFYING, ActionState.FAILED, ActionState.OUTCOME_UNKNOWN}
    ),
    ActionState.OUTCOME_UNKNOWN: frozenset({ActionState.VERIFYING, ActionState.FAILED}),
    ActionState.VERIFYING: frozenset({ActionState.COMPLETED, ActionState.FAILED}),
}


def require_transition(
    current: ActionState, target: ActionState, *, verdict: str | None = None
) -> None:
    """Permit declared transitions only, requiring passing verification for completion."""
    if target not in _TRANSITIONS.get(current, frozenset()):
        raise ValueError(f"Invalid action transition: {current} -> {target}")
    if target == ActionState.COMPLETED and verdict != "pass":
        raise ValueError("Completion requires passing independent verification")
