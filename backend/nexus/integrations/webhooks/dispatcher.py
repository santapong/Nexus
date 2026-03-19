"""Async webhook delivery engine with HMAC signing and retry.

Delivers webhook events to registered subscription URLs with:
- HMAC-SHA256 signature in X-Nexus-Signature header
- Exponential backoff retry (3 attempts: 2s, 4s, 8s)
- Automatic deactivation after 10 consecutive failures
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from datetime import UTC, datetime
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import WebhookSubscription
from nexus.integrations.webhooks.schemas import WebhookEventType, WebhookPayload

logger = structlog.get_logger()

_MAX_RETRIES = 3
_BACKOFF_BASE = 2  # seconds
_MAX_CONSECUTIVE_FAILURES = 10


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Create HMAC-SHA256 signature for webhook payload.

    Args:
        payload_bytes: JSON-encoded payload.
        secret: Webhook signing secret.

    Returns:
        Hex-encoded HMAC signature.
    """
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


async def _deliver_single(
    url: str,
    payload: WebhookPayload,
    secret_hash: str,
) -> bool:
    """Deliver a webhook to a single URL with retry.

    Args:
        url: Target URL.
        payload: Webhook payload to deliver.
        secret_hash: HMAC signing secret.

    Returns:
        True if delivery succeeded.
    """
    import httpx

    payload_bytes = payload.model_dump_json().encode()
    signature = _sign_payload(payload_bytes, secret_hash)

    headers = {
        "Content-Type": "application/json",
        "X-Nexus-Signature": f"sha256={signature}",
        "X-Nexus-Event": payload.event_type,
        "X-Nexus-Delivery": payload.event_id,
    }

    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, content=payload_bytes, headers=headers)
                if resp.status_code < 300:
                    logger.info(
                        "webhook_delivered",
                        url=url,
                        event_type=payload.event_type,
                        status_code=resp.status_code,
                        attempt=attempt + 1,
                    )
                    return True
                logger.warning(
                    "webhook_delivery_failed",
                    url=url,
                    status_code=resp.status_code,
                    attempt=attempt + 1,
                )
        except Exception as exc:
            logger.warning(
                "webhook_delivery_error",
                url=url,
                error=str(exc),
                attempt=attempt + 1,
            )

        if attempt < _MAX_RETRIES - 1:
            backoff = _BACKOFF_BASE ** (attempt + 1)
            await asyncio.sleep(backoff)

    return False


async def dispatch_event(
    workspace_id: str,
    event_type: WebhookEventType,
    data: dict,
    db_session: AsyncSession,
) -> int:
    """Dispatch a webhook event to all matching subscriptions.

    Finds active subscriptions for the workspace that subscribe to the
    event type, then delivers the payload asynchronously to each.

    Args:
        workspace_id: Workspace UUID.
        event_type: Type of event being dispatched.
        data: Event-specific data payload.
        db_session: Database session.

    Returns:
        Number of successful deliveries.
    """
    stmt = select(WebhookSubscription).where(
        WebhookSubscription.workspace_id == workspace_id,
        WebhookSubscription.is_active.is_(True),
    )
    result = await db_session.execute(stmt)
    subscriptions = list(result.scalars().all())

    # Filter by event type
    matching = [sub for sub in subscriptions if event_type in sub.events or "*" in sub.events]

    if not matching:
        return 0

    payload = WebhookPayload(
        event_id=str(uuid4()),
        event_type=event_type,
        workspace_id=workspace_id,
        timestamp=datetime.now(UTC).isoformat(),
        data=data,
    )

    success_count = 0
    for sub in matching:
        delivered = await _deliver_single(sub.url, payload, sub.secret_hash)

        if delivered:
            success_count += 1
            sub.failure_count = 0
            sub.last_triggered_at = datetime.now(UTC)
        else:
            sub.failure_count = (sub.failure_count or 0) + 1
            if sub.failure_count >= _MAX_CONSECUTIVE_FAILURES:
                sub.is_active = False
                logger.warning(
                    "webhook_subscription_deactivated",
                    subscription_id=str(sub.id),
                    url=sub.url,
                    failure_count=sub.failure_count,
                )

    await db_session.flush()

    logger.info(
        "webhook_dispatch_complete",
        workspace_id=workspace_id,
        event_type=event_type,
        total=len(matching),
        succeeded=success_count,
    )

    return success_count
