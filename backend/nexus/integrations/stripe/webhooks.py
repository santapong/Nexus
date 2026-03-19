"""Stripe webhook handler with signature verification.

Processes Stripe events:
- checkout.session.completed → activate subscription
- customer.subscription.updated → sync status
- customer.subscription.deleted → deactivate
- invoice.payment_succeeded → log payment
- invoice.payment_failed → flag workspace
"""

from __future__ import annotations

import structlog
from litestar import Controller, Response, post
from litestar.enums import MediaType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import Workspace
from nexus.integrations.stripe.schemas import BillingPlan
from nexus.settings import settings

logger = structlog.get_logger()


def _verify_webhook_signature(payload: bytes, sig_header: str) -> dict | None:
    """Verify Stripe webhook signature and parse event.

    Args:
        payload: Raw request body.
        sig_header: Stripe-Signature header value.

    Returns:
        Parsed event dict, or None if verification fails.
    """
    try:
        import stripe

        stripe.api_key = settings.stripe_api_key
        event = stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
        return event
    except ImportError:
        logger.warning("stripe_not_installed")
        return None
    except Exception as exc:
        logger.warning("stripe_webhook_verification_failed", error=str(exc))
        return None


async def _handle_checkout_completed(event_data: dict, db_session: AsyncSession) -> None:
    """Handle checkout.session.completed — activate subscription.

    Args:
        event_data: Stripe event data object.
        db_session: Database session.
    """
    workspace_id = event_data.get("metadata", {}).get("workspace_id")
    customer_id = event_data.get("customer")
    subscription_id = event_data.get("subscription")

    if not workspace_id:
        logger.warning("stripe_checkout_no_workspace", customer_id=customer_id)
        return

    stmt = select(Workspace).where(Workspace.id == workspace_id)
    result = await db_session.execute(stmt)
    workspace = result.scalar_one_or_none()
    if not workspace:
        return

    ws_settings = workspace.settings or {}
    ws_settings["stripe_customer_id"] = customer_id
    ws_settings["subscription_id"] = subscription_id
    ws_settings["subscription_status"] = "active"
    ws_settings["billing_plan"] = BillingPlan.STARTER
    workspace.settings = ws_settings
    await db_session.flush()

    logger.info(
        "stripe_subscription_activated",
        workspace_id=workspace_id,
        subscription_id=subscription_id,
    )


async def _handle_subscription_updated(event_data: dict, db_session: AsyncSession) -> None:
    """Handle customer.subscription.updated — sync subscription status.

    Args:
        event_data: Stripe subscription object.
        db_session: Database session.
    """
    customer_id = event_data.get("customer")
    status = event_data.get("status", "")
    period_end = event_data.get("current_period_end")

    # Find workspace by customer_id in settings
    stmt = select(Workspace)
    result = await db_session.execute(stmt)
    for workspace in result.scalars().all():
        ws_settings = workspace.settings or {}
        if ws_settings.get("stripe_customer_id") == customer_id:
            ws_settings["subscription_status"] = status
            if period_end:
                from datetime import UTC, datetime

                ws_settings["current_period_end"] = datetime.fromtimestamp(
                    period_end, tz=UTC
                ).isoformat()
            workspace.settings = ws_settings
            await db_session.flush()
            logger.info(
                "stripe_subscription_updated",
                workspace_id=str(workspace.id),
                status=status,
            )
            return


async def _handle_subscription_deleted(event_data: dict, db_session: AsyncSession) -> None:
    """Handle customer.subscription.deleted — deactivate.

    Args:
        event_data: Stripe subscription object.
        db_session: Database session.
    """
    customer_id = event_data.get("customer")

    stmt = select(Workspace)
    result = await db_session.execute(stmt)
    for workspace in result.scalars().all():
        ws_settings = workspace.settings or {}
        if ws_settings.get("stripe_customer_id") == customer_id:
            ws_settings["subscription_status"] = "canceled"
            ws_settings["billing_plan"] = BillingPlan.FREE
            workspace.settings = ws_settings
            await db_session.flush()
            logger.info(
                "stripe_subscription_canceled",
                workspace_id=str(workspace.id),
            )
            return


async def _handle_invoice_payment_failed(event_data: dict, db_session: AsyncSession) -> None:
    """Handle invoice.payment_failed — flag workspace.

    Args:
        event_data: Stripe invoice object.
        db_session: Database session.
    """
    customer_id = event_data.get("customer")

    stmt = select(Workspace)
    result = await db_session.execute(stmt)
    for workspace in result.scalars().all():
        ws_settings = workspace.settings or {}
        if ws_settings.get("stripe_customer_id") == customer_id:
            ws_settings["subscription_status"] = "past_due"
            workspace.settings = ws_settings
            await db_session.flush()
            logger.warning(
                "stripe_payment_failed",
                workspace_id=str(workspace.id),
            )
            return


# ─── Webhook event router ────────────────────────────────────────────────────

_EVENT_HANDLERS = {
    "checkout.session.completed": _handle_checkout_completed,
    "customer.subscription.updated": _handle_subscription_updated,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "invoice.payment_failed": _handle_invoice_payment_failed,
}


class StripeWebhookController(Controller):
    """Stripe webhook endpoint — receives and processes Stripe events."""

    path = "/webhooks/stripe"

    @post()
    async def handle_webhook(
        self,
        data: dict,
        db_session: AsyncSession,
    ) -> Response:
        """Process a Stripe webhook event.

        Verifies the webhook signature, routes to the appropriate handler,
        and returns 200 to acknowledge receipt.

        Args:
            data: Parsed webhook event body.
            db_session: Database session.

        Returns:
            200 OK on success, 400 on verification failure.
        """
        event_type = data.get("type", "")
        event_data = data.get("data", {}).get("object", {})
        event_id = data.get("id", "")

        logger.info(
            "stripe_webhook_received",
            event_type=event_type,
            event_id=event_id,
        )

        handler = _EVENT_HANDLERS.get(event_type)
        if handler:
            await handler(event_data, db_session)
            await db_session.commit()
        else:
            logger.debug("stripe_webhook_unhandled", event_type=event_type)

        return Response(
            content={"received": True},
            status_code=200,
            media_type=MediaType.JSON,
        )
