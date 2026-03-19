"""Pydantic schemas for Stripe billing integration.

Covers: customer creation, subscription management, usage-based metering,
checkout sessions, and webhook event parsing.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    TRIALING = "trialing"
    INCOMPLETE = "incomplete"


class BillingPlan(StrEnum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


# ─── Request schemas ─────────────────────────────────────────────────────────


class CreateCheckoutRequest(BaseModel):
    """Request to create a Stripe Checkout session."""

    plan: BillingPlan
    success_url: str = "http://localhost:5173/billing/success"
    cancel_url: str = "http://localhost:5173/billing/cancel"


class CreatePortalRequest(BaseModel):
    """Request to create a Stripe Customer Portal session."""

    return_url: str = "http://localhost:5173/billing"


# ─── Response schemas ────────────────────────────────────────────────────────


class StripeCustomerResponse(BaseModel):
    """Stripe customer info for a workspace."""

    workspace_id: str
    stripe_customer_id: str | None
    subscription_status: SubscriptionStatus | None
    current_plan: BillingPlan
    current_period_end: str | None


class CheckoutSessionResponse(BaseModel):
    """Response with Stripe Checkout URL."""

    checkout_url: str
    session_id: str


class PortalSessionResponse(BaseModel):
    """Response with Stripe Customer Portal URL."""

    portal_url: str


class UsageRecordResponse(BaseModel):
    """Response after recording usage."""

    workspace_id: str
    quantity: int
    timestamp: str


# ─── Webhook event schemas ───────────────────────────────────────────────────


class StripeWebhookEvent(BaseModel):
    """Parsed Stripe webhook event."""

    event_id: str
    event_type: str
    customer_id: str | None = None
    subscription_id: str | None = None
    invoice_id: str | None = None
    amount_paid: int | None = None  # cents
    currency: str = "usd"
    raw_data: dict[str, Any] | None = None
