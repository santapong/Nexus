"""Safe response parsing; no provider error text or email contents escape the adapter."""

import hashlib
import json
from typing import Any, cast, get_args
from uuid import UUID

from nexus.company.notifications.contracts import NotificationPayload
from nexus.company.notifications.delivery_contracts import (
    DeliveryState,
    ProviderEvent,
    StatusResult,
    SubmissionResult,
)


def _object(raw: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def submission_response(status: int, raw: bytes) -> SubmissionResult:
    digest = hashlib.sha256(raw).hexdigest()
    value = _object(raw)
    if 200 <= status < 300 and value is not None:
        try:
            provider_id = UUID(value["id"]) if isinstance(value.get("id"), str) else None
        except ValueError:
            provider_id = None
        if provider_id is not None:
            return SubmissionResult(
                outcome="accepted",
                reason="accepted",
                provider_id=provider_id,
                response_sha256=digest,
            )
    error = value.get("name") if value is not None else None
    if status == 409 and error == "invalid_idempotent_request":
        return SubmissionResult(
            outcome="rejected", reason="provider_conflict", response_sha256=digest
        )
    if status == 409 and error == "concurrent_idempotent_requests":
        return SubmissionResult(
            outcome="unknown", reason="concurrent_unknown", response_sha256=digest
        )
    known_errors = {
        "validation_error",
        "invalid_idempotency_key",
        "missing_api_key",
        "invalid_api_key",
        "restricted_api_key",
        "invalid_permission",
        "domain_not_verified",
        "rate_limit_exceeded",
        "daily_quota_exceeded",
        "monthly_quota_exceeded",
    }
    if 400 <= status < 500 and isinstance(error, str) and error in known_errors:
        return SubmissionResult(
            outcome="rejected", reason="provider_rejected", response_sha256=digest
        )
    return SubmissionResult(
        outcome="unknown",
        reason="invalid_response" if status < 300 else "provider_unknown",
        response_sha256=digest,
    )


def status_response(
    status: int, raw: bytes, payload: NotificationPayload, provider_id: UUID
) -> StatusResult:
    value = _object(raw)
    if status != 200 or value is None:
        return StatusResult(
            outcome="unavailable", reason="lookup_unavailable", provider_id=provider_id
        )
    exact = (
        value.get("id") == str(provider_id)
        and value.get("object") == "email"
        and value.get("from") == payload.sender
        and value.get("to") == [payload.recipient]
        and value.get("subject") == payload.subject
        and value.get("text") == payload.text
        and value.get("html") in (None, "")
        and value.get("cc", []) == []
        and value.get("bcc", []) == []
        and value.get("reply_to", []) in ([], None)
    )
    event = value.get("last_event")
    if not exact:
        return StatusResult(
            outcome="unavailable", reason="content_mismatch", provider_id=provider_id
        )
    if not isinstance(event, str) or event not in get_args(ProviderEvent):
        return StatusResult(
            outcome="unavailable", reason="invalid_response", provider_id=provider_id
        )
    states: dict[str, DeliveryState] = {
        "delivered": "delivered",
        "delivery_delayed": "delayed",
        "bounced": "bounced",
        "failed": "failed",
        "suppressed": "suppressed",
        "complained": "complained",
        "canceled": "failed",
    }
    return StatusResult(
        outcome="observed",
        reason="observed",
        provider_id=provider_id,
        provider_event=cast(ProviderEvent, event),
        delivery_state=states.get(event, "unknown"),
        response_sha256=hashlib.sha256(raw).hexdigest(),
    )
