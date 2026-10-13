"""Plan proposals are immutable JSON; only approved registration has native work bindings."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.governance_models import (
    ManagementCharterRevision,
    ManagementGoalHead,
    ManagementGoalRevision,
    ManagementMandateRevision,
)
from nexus.company.management.model_base import CompanyRow, ManagementBase, RecordedRow, scoped_fk
from nexus.execution.runtime_models import ExecutionWork


class ManagementProcedure(CompanyRow, RecordedRow, ManagementBase):
    __tablename__ = "company_management_procedures"
    procedure_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    goal_id: Mapped[UUID] = mapped_column(Uuid)
    parent_task_id: Mapped[UUID] = mapped_column(Uuid)
    parent_run_id: Mapped[UUID] = mapped_column(Uuid)
    allocation_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    quota_json: Mapped[str] = mapped_column(Text)
    binding_json: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("company_id", "goal_id", name="uq_management_one_goal_procedure"),
        UniqueConstraint(
            "company_id", "goal_id", "procedure_id", name="uq_management_procedure_goal_scope"
        ),
        UniqueConstraint("company_id", "parent_task_id", name="uq_management_procedure_parent"),
        UniqueConstraint(
            "company_id",
            "procedure_id",
            "parent_task_id",
            "parent_run_id",
            name="uq_management_procedure_root_scope",
        ),
        CheckConstraint(
            "allocation_usd >= 0 AND allocation_usd <= 5", name="ck_management_procedure_usd"
        ),
    )


class ManagementPlanRevision(CompanyRow, RecordedRow, ManagementBase):
    __tablename__ = "company_management_plan_revisions"
    plan_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    plan_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer)
    goal_id: Mapped[UUID] = mapped_column(Uuid)
    goal_revision_id: Mapped[UUID] = mapped_column(Uuid)
    mandate_revision_id: Mapped[UUID] = mapped_column(Uuid)
    sha256: Mapped[str] = mapped_column(String(64))
    snapshot_json: Mapped[str] = mapped_column(Text)
    proposed_by: Mapped[UUID] = mapped_column(Uuid)
    __table_args__ = (
        Index("ix_management_plan_goal", "company_id", "goal_id"),
        UniqueConstraint("company_id", "plan_id", "revision", name="uq_management_plan_revision"),
        UniqueConstraint(
            "company_id", "plan_id", "plan_revision_id", "goal_id", name="uq_management_plan_scope"
        ),
        UniqueConstraint(
            "company_id", "plan_revision_id", "goal_id", name="uq_management_revision_goal_scope"
        ),
        CheckConstraint("revision > 0 AND length(sha256) = 64", name="ck_management_plan_shape"),
    )


class ManagementOwnerDecision(CompanyRow, RecordedRow, ManagementBase):
    __tablename__ = "company_management_owner_decisions"
    decision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    plan_revision_id: Mapped[UUID] = mapped_column(Uuid)
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(500))
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "plan_revision_id",
            "decision_id",
            name="uq_management_decision_plan_scope",
        ),
        CheckConstraint("kind IN ('approve','revoke')", name="ck_management_owner_decision"),
    )


class ManagementPlanHead(CompanyRow, ManagementBase):
    __tablename__ = "company_management_plan_heads"
    plan_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    current_revision_id: Mapped[UUID] = mapped_column(Uuid)
    goal_id: Mapped[UUID] = mapped_column(Uuid)
    procedure_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    decision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    state: Mapped[str] = mapped_column(String(16))
    __table_args__ = (
        CheckConstraint(
            "state IN ('proposed','approved','revoked') AND "
            "((state='proposed' AND decision_id IS NULL) OR "
            "(state IN ('approved','revoked') AND decision_id IS NOT NULL)) AND "
            "(state <> 'approved' OR procedure_id IS NOT NULL)",
            name="ck_management_plan_lifecycle",
        ),
    )


class ManagementPlanTask(CompanyRow, ManagementBase):
    __tablename__ = "company_management_plan_tasks"
    plan_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    goal_id: Mapped[UUID] = mapped_column(Uuid)
    procedure_id: Mapped[UUID] = mapped_column(Uuid)
    department_id: Mapped[UUID] = mapped_column(Uuid)
    charter_revision_id: Mapped[UUID] = mapped_column(Uuid)
    allocation_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    quota_json: Mapped[str] = mapped_column(Text)
    binding_json: Mapped[str] = mapped_column(Text)
    work_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        Index("ix_management_task_lookup", "company_id", "task_id"),
        Index("ix_management_task_procedure", "company_id", "procedure_id"),
        CheckConstraint(
            "allocation_usd >= 0 AND allocation_usd <= 5", name="ck_management_plan_task_usd"
        ),
    )


class ManagementPlanDependency(CompanyRow, ManagementBase):
    __tablename__ = "company_management_plan_dependencies"
    plan_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    dependency_task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    __table_args__ = (
        CheckConstraint("task_id <> dependency_task_id", name="ck_management_dependency_distinct"),
    )


class ManagementVerificationBinding(CompanyRow, ManagementBase):
    __tablename__ = "company_management_verification_bindings"
    plan_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    verifier_task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    author_task_id: Mapped[UUID] = mapped_column(Uuid)
    check_recipe: Mapped[str] = mapped_column(String(128))
    __table_args__ = (
        CheckConstraint(
            "author_task_id <> verifier_task_id", name="ck_management_verifier_work_distinct"
        ),
    )


class ManagementRevisionEvent(CompanyRow, RecordedRow, ManagementBase):
    __tablename__ = "company_management_revision_events"
    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    procedure_id: Mapped[UUID] = mapped_column(Uuid)
    parent_task_id: Mapped[UUID] = mapped_column(Uuid)
    parent_run_id: Mapped[UUID] = mapped_column(Uuid)
    previous_plan_revision_id: Mapped[UUID] = mapped_column(Uuid)
    next_plan_revision_id: Mapped[UUID] = mapped_column(Uuid)
    owner_decision_id: Mapped[UUID] = mapped_column(Uuid)
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    revision_counter: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "procedure_id",
            "revision_counter",
            name="uq_management_admin_revision_use",
        ),
        CheckConstraint(
            "revision_counter BETWEEN 1 AND 2 AND "
            "previous_plan_revision_id <> next_plan_revision_id",
            name="ck_management_admin_revision",
        ),
    )


scoped_fk(
    ManagementProcedure.__table__,
    ("company_id", "goal_id"),
    ManagementGoalHead.__table__,
    ("company_id", "goal_id"),
    "fk_management_procedure_goal",
)
scoped_fk(
    ManagementProcedure.__table__,
    ("company_id", "parent_task_id", "parent_run_id"),
    ExecutionWork.__table__,
    ("company_id", "task_id", "run_id"),
    "fk_management_procedure_parent_run",
    deferred=True,
)
scoped_fk(
    ManagementPlanRevision.__table__,
    ("company_id", "goal_id", "goal_revision_id"),
    ManagementGoalRevision.__table__,
    ("company_id", "goal_id", "revision_id"),
    "fk_management_plan_goal",
)
scoped_fk(
    ManagementPlanRevision.__table__,
    ("company_id", "mandate_revision_id"),
    ManagementMandateRevision.__table__,
    ("company_id", "revision_id"),
    "fk_management_plan_mandate",
)
scoped_fk(
    ManagementPlanRevision.__table__,
    ("company_id", "proposed_by"),
    DirectoryMembership.__table__,
    ("company_id", "principal_id"),
    "fk_management_plan_proposer",
)
scoped_fk(
    ManagementPlanHead.__table__,
    ("company_id", "plan_id", "current_revision_id", "goal_id"),
    ManagementPlanRevision.__table__,
    ("company_id", "plan_id", "plan_revision_id", "goal_id"),
    "fk_management_plan_head",
    deferred=True,
)
scoped_fk(
    ManagementPlanHead.__table__,
    ("company_id", "goal_id", "procedure_id"),
    ManagementProcedure.__table__,
    ("company_id", "goal_id", "procedure_id"),
    "fk_management_plan_head_procedure",
)
scoped_fk(
    ManagementPlanHead.__table__,
    ("company_id", "current_revision_id", "decision_id"),
    ManagementOwnerDecision.__table__,
    ("company_id", "plan_revision_id", "decision_id"),
    "fk_management_plan_head_decision",
    deferred=True,
)
for owner_row, field in (
    (ManagementOwnerDecision, "owner_id"),
    (ManagementRevisionEvent, "owner_id"),
):
    scoped_fk(
        owner_row.__table__,
        ("company_id", field),
        DirectoryMembership.__table__,
        ("company_id", "principal_id"),
        f"fk_{owner_row.__tablename__}_owner",
    )
scoped_fk(
    ManagementOwnerDecision.__table__,
    ("company_id", "plan_revision_id"),
    ManagementPlanRevision.__table__,
    ("company_id", "plan_revision_id"),
    "fk_management_decision_plan",
)
scoped_fk(
    ManagementPlanTask.__table__,
    ("company_id", "goal_id", "procedure_id"),
    ManagementProcedure.__table__,
    ("company_id", "goal_id", "procedure_id"),
    "fk_management_task_goal_procedure",
)
scoped_fk(
    ManagementRevisionEvent.__table__,
    ("company_id", "procedure_id", "parent_task_id", "parent_run_id"),
    ManagementProcedure.__table__,
    ("company_id", "procedure_id", "parent_task_id", "parent_run_id"),
    "fk_management_revision_exact_root",
)
scoped_fk(
    ManagementPlanTask.__table__,
    ("company_id", "plan_revision_id", "goal_id"),
    ManagementPlanRevision.__table__,
    ("company_id", "plan_revision_id", "goal_id"),
    "fk_management_task_plan",
)
scoped_fk(
    ManagementPlanTask.__table__,
    ("company_id", "task_id", "run_id"),
    ExecutionWork.__table__,
    ("company_id", "task_id", "run_id"),
    "fk_management_task_run",
    deferred=True,
)
scoped_fk(
    ManagementPlanTask.__table__,
    ("company_id", "department_id", "charter_revision_id"),
    ManagementCharterRevision.__table__,
    ("company_id", "department_id", "revision_id"),
    "fk_management_task_charter",
)
for edge_row, fields in (
    (ManagementPlanDependency, ("task_id", "dependency_task_id")),
    (ManagementVerificationBinding, ("author_task_id", "verifier_task_id")),
):
    for field in fields:
        scoped_fk(
            edge_row.__table__,
            ("company_id", "plan_revision_id", field),
            ManagementPlanTask.__table__,
            ("company_id", "plan_revision_id", "task_id"),
            f"fk_{edge_row.__tablename__}_{field}",
        )
for field in ("previous_plan_revision_id", "next_plan_revision_id"):
    scoped_fk(
        ManagementRevisionEvent.__table__,
        ("company_id", field),
        ManagementPlanRevision.__table__,
        ("company_id", "plan_revision_id"),
        f"fk_management_revision_{field}",
    )
scoped_fk(
    ManagementRevisionEvent.__table__,
    ("company_id", "owner_decision_id"),
    ManagementOwnerDecision.__table__,
    ("company_id", "decision_id"),
    "fk_management_revision_decision",
)
scoped_fk(
    ManagementRevisionEvent.__table__,
    ("company_id", "parent_task_id", "parent_run_id"),
    ExecutionWork.__table__,
    ("company_id", "task_id", "run_id"),
    "fk_management_revision_parent",
)
