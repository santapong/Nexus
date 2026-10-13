"""Server-owned, versioned JSON snapshots and approval digests."""

from __future__ import annotations

import hashlib
import json

from nexus.company.contracts.actions import ActionProposal


def canonical_action(action: ActionProposal) -> str:
    """Normalize one validated proposal without trusting a caller-supplied digest.

    This is Nexus's own versioned canonicalization, not an RFC 8785/JCS claim.
    JSON numeric types remain significant; resource-precondition order is normalized.
    """
    snapshot = ActionProposal.model_validate_json(action.model_dump_json())
    payload = snapshot.model_dump(mode="json")
    payload["preconditions"] = sorted(payload["preconditions"], key=lambda item: item["resource"])
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def action_hash(action: ActionProposal) -> str:
    """Hash every bound field in the normalized UTF-8 action snapshot."""
    return hashlib.sha256(canonical_action(action).encode("utf-8")).hexdigest()
