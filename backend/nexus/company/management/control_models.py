"""ID-only actual owner control history with exact native subject/version references."""

from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.governance_models import (
    ManagementCharterRevision,
    ManagementGoalRevision,
    ManagementMandateRevision,
)
from nexus.company.management.model_base import CompanyRow, ManagementBase, RecordedRow, scoped_fk


class ManagementControlEvent(CompanyRow, RecordedRow, ManagementBase):
    __tablename__ = "company_management_control_events"
    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(16))
    subject_kind: Mapped[str] = mapped_column(String(16))
    mandate_revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    previous_mandate_revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    department_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    charter_revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    previous_charter_revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    goal_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    goal_revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    previous_goal_revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    operation_id: Mapped[UUID] = mapped_column(Uuid)
    trace_id: Mapped[UUID] = mapped_column(Uuid)
    deduplication_key: Mapped[str] = mapped_column(String(128))
    __table_args__ = (
        UniqueConstraint("company_id", "sequence", name="uq_management_control_sequence"),
        UniqueConstraint("company_id", "deduplication_key", name="uq_management_control_dedup"),
        CheckConstraint(
            "sequence > 0 AND kind IN ('publish','revoke','reactivate')",
            name="ck_management_control_kind",
        ),
        CheckConstraint(
            "(subject_kind='mandate' AND mandate_revision_id IS NOT NULL AND department_id "
            "IS NULL AND charter_revision_id IS NULL AND previous_charter_revision_id IS "
            "NULL AND goal_id IS NULL AND goal_revision_id IS NULL AND "
            "previous_goal_revision_id IS NULL) OR "
            "(subject_kind='charter' AND department_id IS NOT NULL AND charter_revision_id "
            "IS NOT NULL AND mandate_revision_id IS NULL AND previous_mandate_revision_id "
            "IS NULL AND goal_id IS NULL AND goal_revision_id IS NULL AND "
            "previous_goal_revision_id IS NULL) OR "
            "(subject_kind='goal' AND goal_id IS NOT NULL AND goal_revision_id IS NOT NULL AND "
            "mandate_revision_id IS NULL AND previous_mandate_revision_id IS NULL AND "
            "department_id IS NULL AND charter_revision_id IS NULL AND "
            "previous_charter_revision_id IS NULL)",
            name="ck_management_control_subject",
        ),
        CheckConstraint(
            "kind='publish' OR (subject_kind='mandate' AND previous_mandate_revision_id IS NOT "
            "NULL AND previous_mandate_revision_id=mandate_revision_id) OR "
            "(subject_kind='charter' AND previous_charter_revision_id IS NOT NULL AND "
            "previous_charter_revision_id=charter_revision_id) OR (subject_kind='goal' AND "
            "previous_goal_revision_id IS NOT NULL AND "
            "previous_goal_revision_id=goal_revision_id)",
            name="ck_management_control_activity_head",
        ),
    )


scoped_fk(
    ManagementControlEvent.__table__,
    ("company_id", "owner_id"),
    DirectoryMembership.__table__,
    ("company_id", "principal_id"),
    "fk_management_control_actual_member",
)
for field in ("mandate_revision_id", "previous_mandate_revision_id"):
    scoped_fk(
        ManagementControlEvent.__table__,
        ("company_id", field),
        ManagementMandateRevision.__table__,
        ("company_id", "revision_id"),
        f"fk_management_control_{field}",
    )
for field in ("charter_revision_id", "previous_charter_revision_id"):
    scoped_fk(
        ManagementControlEvent.__table__,
        ("company_id", "department_id", field),
        ManagementCharterRevision.__table__,
        ("company_id", "department_id", "revision_id"),
        f"fk_management_control_{field}",
    )
for field in ("goal_revision_id", "previous_goal_revision_id"):
    scoped_fk(
        ManagementControlEvent.__table__,
        ("company_id", "goal_id", field),
        ManagementGoalRevision.__table__,
        ("company_id", "goal_id", "revision_id"),
        f"fk_management_control_{field}",
    )
