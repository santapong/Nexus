"""Billing API — cost tracking and invoice generation.

Endpoints:
- GET  /api/billing/summary       — Workspace billing summary
- GET  /api/billing/records       — List billing records
- GET  /api/billing/invoice       — Generate invoice for a period
- POST /api/billing/stripe-event-check — Idempotency check for Stripe webhook events

All billing queries are scoped to the caller's workspace_id (extracted from the
JWT). RLS provides a defense-in-depth layer at the SQL level, but we still
filter explicitly here because:
  1. RLS requires `SET LOCAL nexus.workspace_id` per session — if a session
     starts without that GUC, RLS would block everything. Explicit filters
     keep the query correct even if the GUC is absent.
  2. Explicit predicates let PostgreSQL use the index on workspace_id, which
     turns full-table scans into single-tenant scans (also a perf win).
  3. Defense-in-depth: a bug in RLS policy setup should not be the only thing
     standing between tenant A and tenant B's invoices.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from litestar import Controller, Request, get, post
from litestar.exceptions import NotAuthorizedException
from litestar.params import Parameter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.auth import require_auth_user
from nexus.core.redis.clients import redis_locks
from nexus.db.models import BillingRecord

logger = structlog.get_logger()

# Pagination hard cap — protects against `?limit=10000` enumeration attacks.
_MAX_LIMIT = 100

# Stripe re-sends webhooks on any 5xx response. Cache processed event IDs in
# Redis db:3 (idempotency keys) for 7 days, which exceeds Stripe's retry window.
_STRIPE_EVENT_TTL_SECONDS = 7 * 24 * 60 * 60


def _require_workspace_id(request: Request[Any, Any, Any]) -> str:
    """Require an authenticated workspace_id from the request JWT.

    Billing data must never be served to anonymous callers — without a workspace
    filter every record across every tenant would be visible. Raises 401 if the
    request lacks a valid Bearer token, or if the token has no workspace_id
    claim.

    Args:
        request: Litestar request object.

    Returns:
        The authenticated user's workspace_id (guaranteed non-empty).

    Raises:
        NotAuthorizedException: If no valid JWT is present or it has no
            workspace_id claim.
    """
    workspace_id = require_auth_user(request).workspace_id
    if not workspace_id:
        raise NotAuthorizedException(detail="No workspace associated with this user")
    return workspace_id


class BillingSummary(BaseModel):
    """Summary of billing costs for a given period."""

    total_cost_usd: float
    total_tasks_billed: int
    by_type: dict[str, float]
    period_start: str
    period_end: str


class BillingRecordResponse(BaseModel):
    """Single billing record representation."""

    id: str
    task_id: str
    amount_usd: float
    description: str
    billing_type: str
    created_at: str


class InvoiceResponse(BaseModel):
    """Generated invoice for a billing period."""

    workspace_id: str
    period_start: str
    period_end: str
    total_amount_usd: float
    line_items: list[BillingRecordResponse]
    generated_at: str


class StripeEventCheckRequest(BaseModel):
    """Request body for Stripe webhook idempotency check."""

    event_id: str


class StripeEventCheckResponse(BaseModel):
    """Response indicating whether a Stripe event has been processed."""

    event_id: str
    already_processed: bool
    marked_now: bool


async def stripe_event_already_processed(event_id: str) -> bool:
    """Check whether a Stripe webhook event has already been processed.

    Stripe re-sends webhooks on any 5xx response from the receiver. The
    standard mitigation is to dedupe on `event.id`, which is stable across
    re-delivery attempts. We keep a 7-day Redis marker (db:3, idempotency
    keys) which exceeds Stripe's retry window.

    Call this at the very top of a Stripe webhook handler:
        if await stripe_event_already_processed(event_id):
            return Response(status_code=200, content={"received": True})
        ... process event ...
        await mark_stripe_event_processed(event_id)

    Args:
        event_id: The Stripe event ID (`evt_...`).

    Returns:
        True if this event has been seen and processed before.
    """
    if not event_id:
        # No event_id means we cannot dedupe — be conservative and let the
        # caller process it. This should never happen with a real Stripe event.
        return False
    key = f"stripe:event:{event_id}"
    return bool(await redis_locks.exists(key))


async def mark_stripe_event_processed(event_id: str) -> None:
    """Mark a Stripe webhook event as processed.

    Args:
        event_id: The Stripe event ID (`evt_...`).
    """
    if not event_id:
        return
    key = f"stripe:event:{event_id}"
    await redis_locks.set(key, "1", ex=_STRIPE_EVENT_TTL_SECONDS)


class BillingController(Controller):
    """Cost tracking and invoice generation endpoints."""

    path = "/billing"

    @get("/summary")
    async def get_billing_summary(
        self,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
        period: str = "30d",
    ) -> BillingSummary:
        """Get billing summary for the current workspace.

        Args:
            request: Litestar request (workspace_id source).
            db_session: Database session.
            period: Lookback window (e.g. '30d'). Defaults to 30 days.

        Returns:
            Workspace-scoped billing summary.
        """
        workspace_id = _require_workspace_id(request)
        days = int(period.replace("d", "")) if period.endswith("d") else 30
        since = datetime.now(UTC) - timedelta(days=days)

        # NOTE: workspace_id filter required even with RLS — see module docstring.
        stmt = select(BillingRecord).where(
            BillingRecord.workspace_id == workspace_id,
            BillingRecord.created_at >= since,
        )
        result = await db_session.execute(stmt)
        records = list(result.scalars().all())

        by_type: dict[str, float] = {}
        total = 0.0
        for record in records:
            total += record.amount_usd
            by_type[record.billing_type] = by_type.get(record.billing_type, 0.0) + record.amount_usd

        return BillingSummary(
            total_cost_usd=round(total, 4),
            total_tasks_billed=len(records),
            by_type={k: round(v, 4) for k, v in by_type.items()},
            period_start=since.isoformat(),
            period_end=datetime.now(UTC).isoformat(),
        )

    @get("/records")
    async def list_billing_records(
        self,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
        limit: int = Parameter(query="limit", default=50, ge=1, le=_MAX_LIMIT),
        offset: int = Parameter(query="offset", default=0, ge=0),
        billing_type: str | None = Parameter(query="billing_type", default=None),
    ) -> list[BillingRecordResponse]:
        """List billing records with optional type filter, scoped to workspace.

        Args:
            request: Litestar request (workspace_id source).
            db_session: Database session.
            limit: Max results per page (default 50, max 100).
            offset: Pagination offset.
            billing_type: Optional billing type filter.

        Returns:
            Page of billing records belonging to the caller's workspace.
        """
        workspace_id = _require_workspace_id(request)

        # NOTE: workspace_id filter required even with RLS — see module docstring.
        stmt = (
            select(BillingRecord)
            .where(BillingRecord.workspace_id == workspace_id)
            .order_by(BillingRecord.created_at.desc())
        )
        if billing_type:
            stmt = stmt.where(BillingRecord.billing_type == billing_type)
        stmt = stmt.offset(offset).limit(limit)

        result = await db_session.execute(stmt)
        records = result.scalars().all()

        return [
            BillingRecordResponse(
                id=str(r.id),
                task_id=str(r.task_id),
                amount_usd=r.amount_usd,
                description=r.description,
                billing_type=r.billing_type,
                created_at=str(r.created_at),
            )
            for r in records
        ]

    @get("/invoice")
    async def generate_invoice(
        self,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
        period: str = "30d",
    ) -> InvoiceResponse:
        """Generate an invoice for a billing period, scoped to workspace.

        Args:
            request: Litestar request (workspace_id source).
            db_session: Database session.
            period: Lookback window (e.g. '30d'). Defaults to 30 days.

        Returns:
            Workspace-scoped invoice with line items.
        """
        workspace_id = _require_workspace_id(request)
        days = int(period.replace("d", "")) if period.endswith("d") else 30
        since = datetime.now(UTC) - timedelta(days=days)
        now = datetime.now(UTC)

        # NOTE: workspace_id filter required even with RLS — see module docstring.
        stmt = (
            select(BillingRecord)
            .where(
                BillingRecord.workspace_id == workspace_id,
                BillingRecord.created_at >= since,
            )
            .order_by(BillingRecord.created_at.asc())
        )
        result = await db_session.execute(stmt)
        records = list(result.scalars().all())

        line_items = [
            BillingRecordResponse(
                id=str(r.id),
                task_id=str(r.task_id),
                amount_usd=r.amount_usd,
                description=r.description,
                billing_type=r.billing_type,
                created_at=str(r.created_at),
            )
            for r in records
        ]

        total = sum(r.amount_usd for r in records)

        return InvoiceResponse(
            workspace_id=workspace_id,
            period_start=since.isoformat(),
            period_end=now.isoformat(),
            total_amount_usd=round(total, 4),
            line_items=line_items,
            generated_at=now.isoformat(),
        )

    @post("/stripe-event-check")
    async def stripe_event_check(
        self,
        data: StripeEventCheckRequest,
    ) -> StripeEventCheckResponse:
        """Idempotency probe for Stripe webhook events.

        Stripe re-sends a webhook on any 5xx response from the receiver. The
        canonical mitigation is to dedupe on `event.id` (stable across
        re-delivery attempts). The Stripe webhook handler should call
        `stripe_event_already_processed(event.id)` at the very top of the
        handler and return 200 immediately if it returns True. After
        processing, call `mark_stripe_event_processed(event.id)`.

        This endpoint exists so the Stripe webhook controller (which lives
        in `integrations/stripe/webhooks.py`, outside this file's lane) can
        delegate idempotency to a single shared implementation, and so the
        deduplication store can be exercised from tests without invoking
        the webhook controller. It marks the event on first sight.

        Args:
            data: Request body containing the Stripe `event_id`.

        Returns:
            Whether the event was already processed and whether we marked it
            now.
        """
        already = await stripe_event_already_processed(data.event_id)
        if not already:
            await mark_stripe_event_processed(data.event_id)
        return StripeEventCheckResponse(
            event_id=data.event_id,
            already_processed=already,
            marked_now=not already,
        )
