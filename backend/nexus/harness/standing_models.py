"""Standing authority metadata; root's additive company_003 owns explicit DDL/guards."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexus.company.directory_models import DirectoryMembership, RegisteredWork


class StandingBase(DeclarativeBase):
    """Separate owned metadata; references use existing table columns across metadata."""


class StandingWorkAuthority(StandingBase):
    """Owner-declared current source revisions for one registered logical work item."""

    __tablename__ = "company_work_authority"
    company_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    plan_id: Mapped[UUID] = mapped_column(Uuid)
    plan_revision: Mapped[int] = mapped_column(Integer)
    charter_id: Mapped[UUID] = mapped_column(Uuid)
    charter_revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "task_id"],
            [RegisteredWork.__table__.c.company_id, RegisteredWork.__table__.c.task_id],
            name="fk_standing_binding_work",
        ),
        CheckConstraint(
            "plan_revision > 0 AND charter_revision > 0", name="ck_standing_binding_revisions"
        ),
    )


class StandingAuthorityGrant(StandingBase):
    """Immutable normalized snapshot; active=False/revoked_at are irreversible."""

    __tablename__ = "company_standing_grants"
    grant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    company_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    task_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    actor_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    snapshot_json: Mapped[str] = mapped_column(Text)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("company_id", "grant_id", name="uq_company_standing_grant_scope"),
        ForeignKeyConstraint(
            ["company_id", "task_id"],
            [RegisteredWork.__table__.c.company_id, RegisteredWork.__table__.c.task_id],
            name="fk_standing_grant_work",
        ),
        ForeignKeyConstraint(
            ["company_id", "actor_id"],
            [
                DirectoryMembership.__table__.c.company_id,
                DirectoryMembership.__table__.c.principal_id,
            ],
            name="fk_standing_grant_actor",
        ),
        CheckConstraint(
            "(active AND revoked_at IS NULL) OR (NOT active AND revoked_at IS NOT NULL)",
            name="ck_standing_revocation",
        ),
    )
