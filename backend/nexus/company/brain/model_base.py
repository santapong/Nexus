"""Uninstalled Brain metadata; root integrates its migration only after M1 gates."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from nexus.harness.journal_models import CompanyControl


class BrainBase(DeclarativeBase):
    """Separate metadata does not alter Alembic head or import a runtime worker."""


class CompanyRow:
    """Native company scope references the actual installed control Column object."""

    @declared_attr
    def company_id(cls) -> Mapped[UUID]:  # noqa: N805 - SQLAlchemy declared_attr receives the class.
        return mapped_column(
            Uuid,
            ForeignKey(CompanyControl.__table__.c.company_id),
            primary_key=True,
            sort_order=-100,
        )


class RecordedRow:
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
