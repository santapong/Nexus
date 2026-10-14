"""Dedicated company-journal tables mirrored by additive Alembic migration 017."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class JournalBase(DeclarativeBase):
    """Separate metadata avoids pulling legacy tables into standalone journal tests."""


class CompanyControl(JournalBase):
    """Company owner, versions, pause and fixed initial spend allowances."""

    __tablename__ = "company_controls"
    company_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    policy_version: Mapped[str] = mapped_column(String(500))
    price_version: Mapped[str] = mapped_column(String(500))
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_cap_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    work_cap_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    __table_args__ = (
        CheckConstraint(
            "daily_cap_usd >= 0 AND daily_cap_usd <= 5 AND work_cap_usd >= 0 "
            "AND work_cap_usd <= daily_cap_usd",
            name="ck_company_caps",
        ),
    )


class JournalAction(JournalBase):
    """Immutable exact snapshot and single-use decision for one logical action."""

    __tablename__ = "company_action_journal"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("company_controls.company_id"), index=True)
    task_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    trace_id: Mapped[UUID] = mapped_column(Uuid)
    proposal_json: Mapped[str] = mapped_column(Text)
    proposal_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32))
    approval_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_company_action_scope"),
        UniqueConstraint("company_id", "id", "task_id", name="uq_company_action_task_scope"),
    )


class DailyBudget(JournalBase):
    """Shared daily allowance keyed by the Bangkok billing date."""

    __tablename__ = "company_daily_budgets"
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("company_controls.company_id"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    held_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal(0))
    spent_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal(0))
    __table_args__ = (CheckConstraint("held_usd >= 0 AND spent_usd >= 0", name="ck_daily_totals"),)


class WorkBudget(JournalBase):
    """Logical task allowance retained across actions, days and service restarts."""

    __tablename__ = "company_work_budgets"
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("company_controls.company_id"), primary_key=True
    )
    task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    held_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal(0))
    spent_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal(0))
    __table_args__ = (CheckConstraint("held_usd >= 0 AND spent_usd >= 0", name="ck_work_totals"),)


class CostHold(JournalBase):
    """Unique action reservation, its billing day and idempotent reconciliation."""

    __tablename__ = "company_cost_holds"
    action_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    company_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    task_id: Mapped[UUID] = mapped_column(Uuid)
    day: Mapped[date] = mapped_column(Date)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    actual_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    state: Mapped[str] = mapped_column(String(20))
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "action_id"],
            ["company_action_journal.company_id", "company_action_journal.id"],
        ),
        ForeignKeyConstraint(
            ["company_id", "day"], ["company_daily_budgets.company_id", "company_daily_budgets.day"]
        ),
        ForeignKeyConstraint(
            ["company_id", "task_id"],
            ["company_work_budgets.company_id", "company_work_budgets.task_id"],
        ),
        CheckConstraint(
            "amount_usd >= 0 AND (actual_usd IS NULL OR actual_usd >= 0)", name="ck_hold_amounts"
        ),
    )
