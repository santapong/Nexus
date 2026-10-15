"""Closed descriptive kinds, byte caps and data errors; no native permission checks."""

import hashlib
import json
from typing import Literal

CycleKind = Literal["presentation", "support"]
LIMITATIONS = ("mechanical_draft_only", "business_readiness_unproven", "owner_review_required")
MAX_BYTES = 262144


class CycleDataError(ValueError):
    """Malformed supplied data only; an authorization error must not be swallowed as this."""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def criteria_for(kind: CycleKind) -> tuple[str, ...]:
    if kind == "presentation":
        suffixes = (
            "schema",
            "engineering-basis",
            "citations-time",
            "demo-claims",
            "export",
            "scope-limits",
        )
    elif kind == "support":
        suffixes = (
            "schema",
            "engineering-basis",
            "citations-time",
            "hypothetical-claims",
            "export",
            "scope-limits",
        )
    else:
        raise ValueError("Unsupported cycle deliverable kind")
    return tuple(f"{kind}.{name}.v1" for name in suffixes)


def bounded_json(raw: bytes, *, maximum: int = MAX_BYTES) -> object:
    if not 0 < len(raw) <= maximum or b"\0" in raw:
        raise CycleDataError("Cycle JSON byte bound differs")
    value = json.loads(raw.decode("utf8"), object_pairs_hook=_unique, parse_constant=_constant)
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > 12000 or depth > 24:
            raise CycleDataError("Cycle JSON structural bound differs")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CycleDataError("Duplicate cycle JSON field")
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise CycleDataError("Nonfinite cycle JSON value")
