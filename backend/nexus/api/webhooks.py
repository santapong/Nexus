"""Webhook subscription management API.

Endpoints:
- GET    /api/webhooks           — List workspace webhook subscriptions
- POST   /api/webhooks           — Create a new webhook subscription
- DELETE /api/webhooks/{id}      — Delete a webhook subscription
- POST   /api/webhooks/{id}/test — Send a test event to a subscription
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from uuid import uuid4

import structlog
from litestar import Controller, Response, delete, get, post
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import WebhookSubscription
from nexus.integrations.webhooks.dispatcher import _deliver_single
from nexus.integrations.webhooks.schemas import WebhookEventType, WebhookPayload

logger = structlog.get_logger()


# ─── Request/Response schemas ────────────────────────────────────────────────


class CreateWebhookRequest(BaseModel):
    """Request to create a webhook subscription."""

    url: str
    events: list[str]  # list of WebhookEventType values or "*"


class WebhookResponse(BaseModel):
    """Webhook subscription details."""

    id: str
    url: str
    events: list[str]
    is_active: bool
    failure_count: int
    last_triggered_at: str | None
    created_at: str
    signing_secret: str | None = None  # Only returned on creation


class WebhookTestResponse(BaseModel):
    """Result of a webhook test delivery."""

    delivered: bool
    event_id: str


# ─── Controller ──────────────────────────────────────────────────────────────


class WebhookController(Controller):
    """Webhook subscription management endpoints."""

    path = "/webhooks"

    @get()
    async def list_webhooks(
        self,
        db_session: AsyncSession,
        workspace_id: str | None = None,
    ) -> list[WebhookResponse]:
        """List all webhook subscriptions for a workspace.

        Args:
            db_session: Database session.
            workspace_id: Optional workspace filter.

        Returns:
            List of webhook subscriptions.
        """
        stmt = select(WebhookSubscription).order_by(WebhookSubscription.created_at.desc())
        if workspace_id:
            stmt = stmt.where(WebhookSubscription.workspace_id == workspace_id)

        result = await db_session.execute(stmt)
        subscriptions = result.scalars().all()

        return [
            WebhookResponse(
                id=str(sub.id),
                url=sub.url,
                events=sub.events,
                is_active=sub.is_active,
                failure_count=sub.failure_count or 0,
                last_triggered_at=str(sub.last_triggered_at) if sub.last_triggered_at else None,
                created_at=str(sub.created_at),
            )
            for sub in subscriptions
        ]

    @post()
    async def create_webhook(
        self,
        data: CreateWebhookRequest,
        db_session: AsyncSession,
    ) -> WebhookResponse:
        """Create a new webhook subscription.

        Generates a signing secret for HMAC verification and returns it
        once on creation. The secret is not retrievable after this point.

        Args:
            data: Webhook creation request.
            db_session: Database session.

        Returns:
            Created webhook with signing secret.
        """
        # Generate signing secret
        signing_secret = os.urandom(32).hex()
        secret_hash = hashlib.sha256(signing_secret.encode()).hexdigest()

        subscription = WebhookSubscription(
            workspace_id="default",  # Set from JWT in production via RLS middleware
            url=data.url,
            events=data.events,
            secret_hash=secret_hash,
        )
        db_session.add(subscription)
        await db_session.flush()
        await db_session.commit()

        logger.info(
            "webhook_subscription_created",
            subscription_id=str(subscription.id),
            url=data.url,
            events=data.events,
        )

        return WebhookResponse(
            id=str(subscription.id),
            url=subscription.url,
            events=subscription.events,
            is_active=True,
            failure_count=0,
            last_triggered_at=None,
            created_at=str(subscription.created_at),
            signing_secret=signing_secret,
        )

    @delete("/{webhook_id:str}")
    async def delete_webhook(
        self,
        webhook_id: str,
        db_session: AsyncSession,
    ) -> Response[None]:
        """Delete a webhook subscription.

        Args:
            webhook_id: Webhook subscription UUID.
            db_session: Database session.

        Returns:
            204 No Content on success.
        """
        stmt = select(WebhookSubscription).where(WebhookSubscription.id == webhook_id)
        result = await db_session.execute(stmt)
        subscription = result.scalar_one_or_none()

        if subscription:
            await db_session.delete(subscription)
            await db_session.commit()
            logger.info("webhook_subscription_deleted", subscription_id=webhook_id)

        return Response(content=None, status_code=204)

    @post("/{webhook_id:str}/test")
    async def test_webhook(
        self,
        webhook_id: str,
        db_session: AsyncSession,
    ) -> WebhookTestResponse:
        """Send a test event to a webhook subscription.

        Args:
            webhook_id: Webhook subscription UUID.
            db_session: Database session.

        Returns:
            Delivery result.
        """
        stmt = select(WebhookSubscription).where(WebhookSubscription.id == webhook_id)
        result = await db_session.execute(stmt)
        subscription = result.scalar_one_or_none()

        if not subscription:
            return WebhookTestResponse(delivered=False, event_id="")

        event_id = str(uuid4())
        test_payload = WebhookPayload(
            event_id=event_id,
            event_type=WebhookEventType.TASK_COMPLETED,
            workspace_id=subscription.workspace_id,
            timestamp=datetime.now(UTC).isoformat(),
            data={
                "task_id": "test-00000000-0000-0000-0000-000000000000",
                "trace_id": "test-trace",
                "status": "completed",
                "instruction_preview": "This is a test webhook delivery.",
                "message": "If you received this, your webhook is working!",
            },
        )

        delivered = await _deliver_single(subscription.url, test_payload, subscription.secret_hash)

        return WebhookTestResponse(delivered=delivered, event_id=event_id)
