"""Commitment history and report projections declare no delivery or spend authority."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.governance_models import ManagementGoalRevision
from nexus.company.management.model_base import CompanyRow, ManagementBase, RecordedRow, scoped_fk
from nexus.company.management.plan_models import ManagementPlanRevision


class ManagementCommitmentRevision(CompanyRow, RecordedRow, ManagementBase):
    __tablename__ = "company_management_commitment_revisions"
    revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    commitment_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[str] = mapped_column(String(128))
    goal_id: Mapped[UUID] = mapped_column(Uuid)
    goal_revision_id: Mapped[UUID] = mapped_column(Uuid)
    plan_revision_id: Mapped[UUID] = mapped_column(Uuid)
    responsible_id: Mapped[UUID] = mapped_column(Uuid)
    sha256: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    actionable_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_by: Mapped[UUID] = mapped_column(Uuid)
    __table_args__ = (
        UniqueConstraint(
            "company_id", "commitment_id", "version", name="uq_management_commitment_version"
        ),
        UniqueConstraint(
            "company_id", "commitment_id", "revision_id", name="uq_management_commitment_scope"
        ),
    )


class ManagementCommitmentHead(CompanyRow, ManagementBase):
    __tablename__ = "company_management_commitment_heads"
    commitment_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    current_revision_id: Mapped[UUID] = mapped_column(Uuid)


class ManagementReportSnapshot(CompanyRow, RecordedRow, ManagementBase):
    __tablename__ = "company_management_report_snapshots"
    report_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64))
    snapshot_json: Mapped[str] = mapped_column(Text)
    created_by: Mapped[UUID] = mapped_column(Uuid)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))


scoped_fk(
    ManagementCommitmentRevision.__table__,
    ("company_id", "goal_id", "goal_revision_id"),
    ManagementGoalRevision.__table__,
    ("company_id", "goal_id", "revision_id"),
    "fk_management_commitment_goal",
)
scoped_fk(
    ManagementCommitmentRevision.__table__,
    ("company_id", "plan_revision_id"),
    ManagementPlanRevision.__table__,
    ("company_id", "plan_revision_id"),
    "fk_management_commitment_plan",
)
for field in ("responsible_id", "recorded_by"):
    scoped_fk(
        ManagementCommitmentRevision.__table__,
        ("company_id", field),
        DirectoryMembership.__table__,
        ("company_id", "principal_id"),
        f"fk_management_commitment_{field}",
    )
scoped_fk(
    ManagementCommitmentHead.__table__,
    ("company_id", "commitment_id", "current_revision_id"),
    ManagementCommitmentRevision.__table__,
    ("company_id", "commitment_id", "revision_id"),
    "fk_management_commitment_head",
    deferred=True,
)
scoped_fk(
    ManagementReportSnapshot.__table__,
    ("company_id", "created_by"),
    DirectoryMembership.__table__,
    ("company_id", "principal_id"),
    "fk_management_report_author",
)
