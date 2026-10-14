"""Append-only native measurement metadata; normal013 installation/guards are Root-owned."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.governance_models import ManagementGoalRevision
from nexus.company.management.model_base import CompanyRow, ManagementBase, RecordedRow, scoped_fk
from nexus.company.management.plan_models import ManagementPlanRevision


class ManagementMetricObservation(CompanyRow, RecordedRow, ManagementBase):
    __tablename__ = "company_management_metric_observations"
    observation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    goal_id: Mapped[UUID] = mapped_column(Uuid)
    goal_revision_id: Mapped[UUID] = mapped_column(Uuid)
    plan_id: Mapped[UUID] = mapped_column(Uuid)
    plan_revision_id: Mapped[UUID] = mapped_column(Uuid)
    metric_id: Mapped[str] = mapped_column(String(128))
    recipe: Mapped[str | None] = mapped_column(String(128), nullable=True)
    selection_count: Mapped[int] = mapped_column(Integer)
    value_kind: Mapped[str] = mapped_column(String(16))
    count_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_sha256: Mapped[str] = mapped_column(String(64))
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    record_sha256: Mapped[str] = mapped_column(String(64))
    request_json: Mapped[str] = mapped_column(Text)
    record_json: Mapped[str] = mapped_column(Text)
    recorded_by: Mapped[UUID] = mapped_column(Uuid)
    operation_id: Mapped[UUID] = mapped_column(Uuid)
    audit_trace_id: Mapped[UUID] = mapped_column(Uuid)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index(
            "ix_management_metric_goal",
            "company_id",
            "goal_id",
            "metric_id",
            "observed_at",
            "observation_id",
        ),
        Index(
            "ix_management_metric_plan",
            "company_id",
            "plan_id",
            "plan_revision_id",
            "goal_id",
            "goal_revision_id",
        ),
        Index("ix_management_metric_goal_ref", "company_id", "goal_id", "goal_revision_id"),
        Index("ix_management_metric_owner", "company_id", "recorded_by"),
        UniqueConstraint("company_id", "operation_id", name="uq_management_metric_operation"),
        CheckConstraint(
            "selection_count BETWEEN 1 AND 100 AND "
            "((value_kind = 'known' AND count_value IS NOT NULL "
            "AND count_value BETWEEN 0 AND selection_count) OR "
            "(value_kind = 'unknown' AND count_value IS NULL))",
            name="ck_management_metric_value",
        ),
        CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$' AND snapshot_sha256 ~ '^[0-9a-f]{64}$' "
            "AND record_sha256 ~ '^[0-9a-f]{64}$' AND length(record_json) <= 4194304",
            name="ck_management_metric_shape",
        ),
    )


scoped_fk(
    ManagementMetricObservation.__table__,
    ("company_id", "goal_id", "goal_revision_id"),
    ManagementGoalRevision.__table__,
    ("company_id", "goal_id", "revision_id"),
    "fk_management_metric_goal",
)
scoped_fk(
    ManagementMetricObservation.__table__,
    ("company_id", "plan_id", "plan_revision_id", "goal_id", "goal_revision_id"),
    ManagementPlanRevision.__table__,
    ("company_id", "plan_id", "plan_revision_id", "goal_id", "goal_revision_id"),
    "fk_management_metric_plan",
)
scoped_fk(
    ManagementMetricObservation.__table__,
    ("company_id", "recorded_by"),
    DirectoryMembership.__table__,
    ("company_id", "principal_id"),
    "fk_management_metric_owner",
)
