"""Current resources/grants are separate from immutable source/evidence bytes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.company.brain.model_base import BrainBase, CompanyRow, RecordedRow
from nexus.company.directory_models import DirectoryMembership


class BrainResource(CompanyRow, BrainBase):
    __tablename__ = "company_brain_resources"
    resource_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    kind: Mapped[str] = mapped_column(String(12))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    acl_generation: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    __table_args__ = (
        CheckConstraint(
            "kind IN ('source','artifact','entity','claim','context')",
            name="ck_brain_resource_kind",
        ),
        CheckConstraint("acl_generation >= 1", name="ck_brain_resource_generation"),
    )


class BrainResourceAccess(CompanyRow, BrainBase):
    __tablename__ = "company_brain_resource_access"
    resource_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    principal_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean)
    generation: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "resource_id"],
            ["company_brain_resources.company_id", "company_brain_resources.resource_id"],
            name="fk_brain_access_resource",
        ),
        ForeignKeyConstraint(
            ["company_id", "principal_id"],
            [
                DirectoryMembership.__table__.c.company_id,
                DirectoryMembership.__table__.c.principal_id,
            ],
            name="fk_brain_access_member",
        ),
        CheckConstraint("generation >= 1", name="ck_brain_access_generation"),
    )


class BrainAccessEvent(CompanyRow, RecordedRow, BrainBase):
    """Append-only owner CAS history; immutability/RLS supplied by root migration."""

    __tablename__ = "company_brain_access_events"
    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    resource_id: Mapped[UUID] = mapped_column(Uuid)
    principal_id: Mapped[UUID] = mapped_column(Uuid)
    generation: Mapped[int] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(Boolean)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    operation_id: Mapped[UUID] = mapped_column(Uuid)
    trace_id: Mapped[UUID] = mapped_column(Uuid)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "resource_id"],
            ["company_brain_resources.company_id", "company_brain_resources.resource_id"],
            name="fk_brain_access_event_resource",
        ),
        ForeignKeyConstraint(
            ["company_id", "principal_id"],
            [
                DirectoryMembership.__table__.c.company_id,
                DirectoryMembership.__table__.c.principal_id,
            ],
            name="fk_brain_access_event_member",
        ),
        ForeignKeyConstraint(
            ["company_id", "owner_id"],
            [
                DirectoryMembership.__table__.c.company_id,
                DirectoryMembership.__table__.c.principal_id,
            ],
            name="fk_brain_access_event_owner",
        ),
        CheckConstraint("generation >= 1", name="ck_brain_access_event_generation"),
    )
