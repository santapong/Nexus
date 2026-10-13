"""Immutable mandate/charter/goal versions and current-pointer declarations only."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from nexus.company.brain.evidence_models import BrainEvidence
from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.model_base import CompanyRow, ManagementBase, RecordedRow, scoped_fk


class ManagementMandateRevision(CompanyRow, RecordedRow, ManagementBase):
    __tablename__ = "company_management_mandate_revisions"
    revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version: Mapped[str] = mapped_column(String(128))
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    sha256: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    recorded_by: Mapped[UUID] = mapped_column(Uuid)
    __table_args__ = (
        UniqueConstraint("company_id", "version", name="uq_management_mandate_version"),
        CheckConstraint(
            "owner_id = recorded_by AND length(sha256) = 64", name="ck_management_mandate_shape"
        ),
    )


class ManagementMandateHead(CompanyRow, ManagementBase):
    __tablename__ = "company_management_mandate_heads"
    current_revision_id: Mapped[UUID] = mapped_column(Uuid)
    active: Mapped[bool] = mapped_column(Boolean)


class ManagementCharterRevision(CompanyRow, RecordedRow, ManagementBase):
    __tablename__ = "company_management_charter_revisions"
    revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    department_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[str] = mapped_column(String(128))
    mandate_revision_id: Mapped[UUID] = mapped_column(Uuid)
    sha256: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    recorded_by: Mapped[UUID] = mapped_column(Uuid)
    __table_args__ = (
        UniqueConstraint(
            "company_id", "department_id", "version", name="uq_management_charter_version"
        ),
        UniqueConstraint(
            "company_id", "department_id", "revision_id", name="uq_management_charter_scope"
        ),
    )


class ManagementCharterHead(CompanyRow, ManagementBase):
    __tablename__ = "company_management_charter_heads"
    department_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    current_revision_id: Mapped[UUID] = mapped_column(Uuid)
    active: Mapped[bool] = mapped_column(Boolean)


class ManagementGoalRevision(CompanyRow, RecordedRow, ManagementBase):
    __tablename__ = "company_management_goal_revisions"
    revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    goal_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[str] = mapped_column(String(128))
    mandate_revision_id: Mapped[UUID] = mapped_column(Uuid)
    responsible_id: Mapped[UUID] = mapped_column(Uuid)
    sha256: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    actionable_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_by: Mapped[UUID] = mapped_column(Uuid)
    __table_args__ = (
        UniqueConstraint("company_id", "goal_id", "version", name="uq_management_goal_version"),
        UniqueConstraint("company_id", "goal_id", "revision_id", name="uq_management_goal_scope"),
    )


class ManagementGoalHead(CompanyRow, ManagementBase):
    __tablename__ = "company_management_goal_heads"
    goal_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    current_revision_id: Mapped[UUID] = mapped_column(Uuid)
    active: Mapped[bool] = mapped_column(Boolean)


class ManagementGoalEvidence(CompanyRow, ManagementBase):
    __tablename__ = "company_management_goal_evidence"
    goal_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    metric_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    evidence_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)


scoped_fk(
    ManagementMandateRevision.__table__,
    ("company_id", "owner_id"),
    DirectoryMembership.__table__,
    ("company_id", "principal_id"),
    "fk_management_mandate_owner",
)
scoped_fk(
    ManagementMandateHead.__table__,
    ("company_id", "current_revision_id"),
    ManagementMandateRevision.__table__,
    ("company_id", "revision_id"),
    "fk_management_mandate_head",
    deferred=True,
)
for row in (ManagementCharterRevision, ManagementGoalRevision):
    scoped_fk(
        row.__table__,
        ("company_id", "mandate_revision_id"),
        ManagementMandateRevision.__table__,
        ("company_id", "revision_id"),
        f"fk_{row.__tablename__}_mandate",
    )
    scoped_fk(
        row.__table__,
        ("company_id", "recorded_by"),
        DirectoryMembership.__table__,
        ("company_id", "principal_id"),
        f"fk_{row.__tablename__}_owner",
    )
scoped_fk(
    ManagementGoalRevision.__table__,
    ("company_id", "responsible_id"),
    DirectoryMembership.__table__,
    ("company_id", "principal_id"),
    "fk_management_goal_responsible",
)
scoped_fk(
    ManagementCharterHead.__table__,
    ("company_id", "department_id", "current_revision_id"),
    ManagementCharterRevision.__table__,
    ("company_id", "department_id", "revision_id"),
    "fk_management_charter_head",
    deferred=True,
)
scoped_fk(
    ManagementGoalHead.__table__,
    ("company_id", "goal_id", "current_revision_id"),
    ManagementGoalRevision.__table__,
    ("company_id", "goal_id", "revision_id"),
    "fk_management_goal_head",
    deferred=True,
)
scoped_fk(
    ManagementGoalEvidence.__table__,
    ("company_id", "goal_revision_id"),
    ManagementGoalRevision.__table__,
    ("company_id", "revision_id"),
    "fk_management_goal_evidence_revision",
)
scoped_fk(
    ManagementGoalEvidence.__table__,
    ("company_id", "evidence_id"),
    BrainEvidence.__table__,
    ("company_id", "evidence_id"),
    "fk_management_goal_evidence_source",
)
