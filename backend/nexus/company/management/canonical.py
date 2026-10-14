"""Exact named management payload identity; a digest alone is never an owner signature."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel


def _value(value: Any, key: str = "") -> Any:
    if isinstance(value, BaseModel):
        return _value(value.model_dump(), key)
    if isinstance(value, dict):
        return {name: _value(item, name) for name, item in value.items()}
    if isinstance(value, (set, frozenset)):
        items = [_value(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
    if isinstance(value, (tuple, list)):
        return [_value(item) for item in value]
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Management values must be finite")
        if value == 0:
            value = Decimal(0)
        return (
            format(value.quantize(Decimal("0.000001")), ".6f")
            if key.endswith("_usd")
            else str(value.normalize())
        )
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("Management instants must be explicitly aware")
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    return value


def canonical_json(payload: BaseModel) -> str:
    return json.dumps(
        {"recipe": "management-canonical-v1", "payload": _value(payload)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_sha256(payload: BaseModel) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()
