"""Billing API — cost tracking and invoice generation.

Endpoints:
- GET  /api/billing/summary       — Workspace billing summary
- GET  /api/billing/records       — List billing records
- GET  /api/billing/invoice       — Generate invoice for a period
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from litestar import Controller, get
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import BillingRecord

logger = structlog.get_logger()


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


class BillingController(Controller):
    """Cost tracking and invoice generation endpoints."""

    path = "/billing"

    @get("/summary")
    async def get_billing_summary(
        self,
        db_session: AsyncSession,
        period: str = "30d",
    ) -> BillingSummary:
        """Get billing summary for the current workspace."""
        days = int(period.replace("d", "")) if period.endswith("d") else 30
        since = datetime.now(UTC) - timedelta(days=days)

        stmt = select(BillingRecord).where(BillingRecord.created_at >= since)
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
        db_session: AsyncSession,
        limit: int = 50,
        billing_type: str | None = None,
    ) -> list[BillingRecordResponse]:
        """List billing records with optional type filter."""
        stmt = select(BillingRecord).order_by(BillingRecord.created_at.desc())
        if billing_type:
            stmt = stmt.where(BillingRecord.billing_type == billing_type)
        stmt = stmt.limit(limit)

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
        db_session: AsyncSession,
        period: str = "30d",
    ) -> InvoiceResponse:
        """Generate an invoice for a billing period."""
        days = int(period.replace("d", "")) if period.endswith("d") else 30
        since = datetime.now(UTC) - timedelta(days=days)
        now = datetime.now(UTC)

        stmt = (
            select(BillingRecord)
            .where(BillingRecord.created_at >= since)
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
            workspace_id="default",
            period_start=since.isoformat(),
            period_end=now.isoformat(),
            total_amount_usd=round(total, 4),
            line_items=line_items,
            generated_at=now.isoformat(),
        )
