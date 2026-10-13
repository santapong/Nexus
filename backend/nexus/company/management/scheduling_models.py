"""Immutable scan receipts; existing namespaced Brain cursors retain stream offsets."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.model_base import CompanyRow, RecordedRow, scoped_fk


class SchedulingBase(DeclarativeBase):
    """A normal additive company010 migration is required before any scan persistence."""


class ManagementSchedulerScan(CompanyRow, RecordedRow, SchedulingBase):
    __tablename__ = "company_management_scheduler_scans"
    scan_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    consumer: Mapped[str] = mapped_column(String(128))
    recipe_version: Mapped[str] = mapped_column(String(128))
    event_key: Mapped[str] = mapped_column(String(128))
    request_sha256: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    operation_id: Mapped[UUID] = mapped_column(Uuid)
    trace_id: Mapped[UUID] = mapped_column(Uuid)
    start_brain_sequence: Mapped[int] = mapped_column(BigInteger)
    end_brain_sequence: Mapped[int] = mapped_column(BigInteger)
    start_control_sequence: Mapped[int] = mapped_column(BigInteger)
    end_control_sequence: Mapped[int] = mapped_column(BigInteger)
    due_bucket: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint(
            "company_id", "consumer", "recipe_version", "event_key", name="uq_management_scan_event"
        ),
        Index("ix_management_scan_owner", "company_id", "owner_id"),
        CheckConstraint(
            "start_brain_sequence >= 0 AND end_brain_sequence >= start_brain_sequence "
            "AND start_control_sequence >= 0 "
            "AND end_control_sequence >= start_control_sequence",
            name="ck_management_scan_sequences",
        ),
        CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$' AND octet_length(result_json) BETWEEN 2 AND 262144",
            name="ck_management_scan_result",
        ),
    )


scoped_fk(
    ManagementSchedulerScan.__table__,
    ("company_id", "owner_id"),
    DirectoryMembership.__table__,
    ("company_id", "principal_id"),
    "fk_management_scan_owner",
)
