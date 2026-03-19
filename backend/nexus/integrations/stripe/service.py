"""Stripe billing service — customer, subscription, and usage management.

All Stripe API calls go through this service. No other module should
import stripe directly. Degrades gracefully when stripe_api_key is empty.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import BillingRecord, Workspace
from nexus.integrations.stripe.schemas import (
    BillingPlan,
    CheckoutSessionResponse,
    CreateCheckoutRequest,
    CreatePortalRequest,
    PortalSessionResponse,
    StripeCustomerResponse,
)
from nexus.settings import settings

logger = structlog.get_logger()


def _get_stripe():  # type: ignore[no-untyped-def]
    """Lazy-load stripe module to avoid import errors when not installed.

    Returns:
        The stripe module, or None if unavailable.
    """
    try:
        import stripe

        if settings.stripe_api_key:
            stripe.api_key = settings.stripe_api_key
            return stripe
    except ImportError:
        pass
    return None


# ─── Plan → Price mapping ────────────────────────────────────────────────────

_PLAN_PRICE_MAP: dict[BillingPlan, str] = {
    BillingPlan.STARTER: "price_starter",  # Override via settings
    BillingPlan.PRO: "price_pro",
    BillingPlan.ENTERPRISE: "price_enterprise",
}


async def get_or_create_customer(
    workspace_id: str,
    db_session: AsyncSession,
) -> str | None:
    """Get or create a Stripe customer for a workspace.

    Args:
        workspace_id: Workspace UUID.
        db_session: Database session.

    Returns:
        Stripe customer ID, or None if Stripe is not configured.
    """
    stripe = _get_stripe()
    if not stripe:
        return None

    stmt = select(Workspace).where(Workspace.id == workspace_id)
    result = await db_session.execute(stmt)
    workspace = result.scalar_one_or_none()
    if not workspace:
        return None

    # Check if workspace already has a Stripe customer
    ws_settings = workspace.settings or {}
    customer_id = ws_settings.get("stripe_customer_id")
    if customer_id:
        return customer_id

    # Create new Stripe customer
    customer = stripe.Customer.create(
        metadata={"workspace_id": workspace_id, "workspace_name": workspace.name},
    )
    customer_id = customer["id"]

    # Store in workspace settings
    ws_settings["stripe_customer_id"] = customer_id
    workspace.settings = ws_settings
    await db_session.flush()

    logger.info(
        "stripe_customer_created",
        workspace_id=workspace_id,
        customer_id=customer_id,
    )

    return customer_id


async def get_billing_status(
    workspace_id: str,
    db_session: AsyncSession,
) -> StripeCustomerResponse:
    """Get billing status for a workspace.

    Args:
        workspace_id: Workspace UUID.
        db_session: Database session.

    Returns:
        Current billing status including plan and subscription info.
    """
    stmt = select(Workspace).where(Workspace.id == workspace_id)
    result = await db_session.execute(stmt)
    workspace = result.scalar_one_or_none()

    if not workspace:
        return StripeCustomerResponse(
            workspace_id=workspace_id,
            stripe_customer_id=None,
            subscription_status=None,
            current_plan=BillingPlan.FREE,
            current_period_end=None,
        )

    ws_settings = workspace.settings or {}
    return StripeCustomerResponse(
        workspace_id=workspace_id,
        stripe_customer_id=ws_settings.get("stripe_customer_id"),
        subscription_status=ws_settings.get("subscription_status"),
        current_plan=ws_settings.get("billing_plan", BillingPlan.FREE),
        current_period_end=ws_settings.get("current_period_end"),
    )


async def create_checkout_session(
    workspace_id: str,
    data: CreateCheckoutRequest,
    db_session: AsyncSession,
) -> CheckoutSessionResponse | None:
    """Create a Stripe Checkout session for subscription purchase.

    Args:
        workspace_id: Workspace UUID.
        data: Checkout request with plan and URLs.
        db_session: Database session.

    Returns:
        Checkout session URL and ID, or None if Stripe unavailable.
    """
    stripe = _get_stripe()
    if not stripe:
        return None

    customer_id = await get_or_create_customer(workspace_id, db_session)
    if not customer_id:
        return None

    price_id = settings.stripe_price_id_per_task
    if data.plan in _PLAN_PRICE_MAP:
        price_id = _PLAN_PRICE_MAP[data.plan]

    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=data.success_url + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=data.cancel_url,
        metadata={"workspace_id": workspace_id},
    )

    logger.info(
        "stripe_checkout_created",
        workspace_id=workspace_id,
        session_id=session["id"],
    )

    return CheckoutSessionResponse(
        checkout_url=session["url"],
        session_id=session["id"],
    )


async def create_portal_session(
    workspace_id: str,
    data: CreatePortalRequest,
    db_session: AsyncSession,
) -> PortalSessionResponse | None:
    """Create a Stripe Customer Portal session for self-service billing.

    Args:
        workspace_id: Workspace UUID.
        data: Portal request with return URL.
        db_session: Database session.

    Returns:
        Portal session URL, or None if Stripe unavailable.
    """
    stripe = _get_stripe()
    if not stripe:
        return None

    customer_id = await get_or_create_customer(workspace_id, db_session)
    if not customer_id:
        return None

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=data.return_url,
    )

    return PortalSessionResponse(portal_url=session["url"])


async def record_task_usage(
    workspace_id: str,
    task_id: str,
    token_cost_usd: float,
    db_session: AsyncSession,
) -> None:
    """Record a task's cost as a billing record.

    Creates a BillingRecord and optionally reports usage to Stripe
    for metered billing.

    Args:
        workspace_id: Workspace UUID.
        task_id: Task UUID.
        token_cost_usd: Cost in USD.
        db_session: Database session.
    """
    record = BillingRecord(
        workspace_id=workspace_id,
        task_id=task_id,
        amount_usd=token_cost_usd,
        description=f"Task execution: {task_id}",
        billing_type="llm_usage",
    )
    db_session.add(record)

    logger.info(
        "billing_usage_recorded",
        workspace_id=workspace_id,
        task_id=task_id,
        amount_usd=token_cost_usd,
    )
