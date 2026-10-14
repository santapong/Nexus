"""One immutable row per owner cancellation operation, never a mutable active-state flag."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexus.company.directory_models import DirectoryMembership, RegisteredWork
from nexus.company.management.model_base import CompanyRow, RecordedRow, scoped_fk
from nexus.execution.runtime_models import ExecutionWork


class CancellationBase(DeclarativeBase):
    """Independent explicit migration metadata; importing it installs no table or policy."""


class WorkCancellation(CompanyRow, RecordedRow, CancellationBase):
    """Permanent native owner instruction with exact immutable run and administrative provenance."""

    __tablename__ = "company_management_cancellations"
    cancellation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    operation_id: Mapped[UUID] = mapped_column(Uuid)
    task_id: Mapped[UUID] = mapped_column(Uuid)
    trace_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    binding_json: Mapped[str] = mapped_column(Text)
    registration_sha256: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(500))
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    audit_trace_id: Mapped[UUID] = mapped_column(Uuid)
    __table_args__ = (
        UniqueConstraint("company_id", "operation_id", name="uq_management_cancel_operation"),
        Index("ix_management_cancel_task", "company_id", "task_id", "recorded_at"),
        Index("ix_management_cancel_owner", "company_id", "owner_id"),
        CheckConstraint("registration_sha256 ~ '^[0-9a-f]{64}$'", name="ck_management_cancel_hash"),
        CheckConstraint(
            "octet_length(binding_json) BETWEEN 2 AND 32768 "
            "AND length(trim(reason)) BETWEEN 1 AND 500",
            name="ck_management_cancel_shape",
        ),
    )


scoped_fk(
    WorkCancellation.__table__,
    ("company_id", "task_id", "run_id"),
    ExecutionWork.__table__,
    ("company_id", "task_id", "run_id"),
    "fk_management_cancel_run",
)
scoped_fk(
    WorkCancellation.__table__,
    ("company_id", "task_id"),
    RegisteredWork.__table__,
    ("company_id", "task_id"),
    "fk_management_cancel_work",
)
scoped_fk(
    WorkCancellation.__table__,
    ("company_id", "owner_id"),
    DirectoryMembership.__table__,
    ("company_id", "principal_id"),
    "fk_management_cancel_owner",
)
