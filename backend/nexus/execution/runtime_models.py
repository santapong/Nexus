"""Company-profile execution metadata; root supplies additive company migration c002."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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
from nexus.harness.journal_models import JournalAction


class ExecutionBase(DeclarativeBase):
    """Isolated metadata references existing native company/registered-action identities."""


class ExecutionWork(ExecutionBase):
    """One immutable logical run; quota slices and consumed attempts never reset."""

    __tablename__ = "company_execution_work"
    company_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    trace_id: Mapped[UUID] = mapped_column(Uuid)
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    workspace_id: Mapped[UUID] = mapped_column(Uuid)
    parent_task_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    registration_json: Mapped[str] = mapped_column(Text)
    registration_hash: Mapped[str] = mapped_column(String(64))
    workflow_name: Mapped[str] = mapped_column(String(500))
    workflow_version: Mapped[str] = mapped_column(String(500))
    model_profile: Mapped[str] = mapped_column(String(500))
    model_registry_version: Mapped[str] = mapped_column(String(500))
    model_requests_limit: Mapped[int] = mapped_column(Integer)
    model_requests_used: Mapped[int] = mapped_column(Integer, default=0)
    model_requests_delegated: Mapped[int] = mapped_column(Integer, default=0)
    tool_attempts_limit: Mapped[int] = mapped_column(Integer)
    tool_attempts_used: Mapped[int] = mapped_column(Integer, default=0)
    tool_attempts_delegated: Mapped[int] = mapped_column(Integer, default=0)
    rework_rounds_limit: Mapped[int] = mapped_column(Integer)
    rework_rounds_used: Mapped[int] = mapped_column(Integer, default=0)
    rework_rounds_delegated: Mapped[int] = mapped_column(Integer, default=0)
    plan_revisions_limit: Mapped[int] = mapped_column(Integer)
    plan_revisions_used: Mapped[int] = mapped_column(Integer, default=0)
    plan_revisions_delegated: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(24), default="eligible", index=True)
    fence: Mapped[int] = mapped_column(BigInteger, default=0)
    worker_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    lease_principal_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    lease_mode: Mapped[str | None] = mapped_column(String(12), nullable=True)
    segment_number: Mapped[int] = mapped_column(Integer, default=0)
    segment_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    waiting_action_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "task_id"],
            [RegisteredWork.__table__.c.company_id, RegisteredWork.__table__.c.task_id],
            name="fk_company_execution_registered_work",
        ),
        ForeignKeyConstraint(
            ["company_id", "parent_task_id"],
            ["company_execution_work.company_id", "company_execution_work.task_id"],
            name="fk_company_execution_parent",
        ),
        ForeignKeyConstraint(
            ["company_id", "lease_principal_id"],
            [
                DirectoryMembership.__table__.c.company_id,
                DirectoryMembership.__table__.c.principal_id,
            ],
            name="fk_company_execution_lease_principal",
        ),
        ForeignKeyConstraint(
            ["company_id", "waiting_action_id"],
            [JournalAction.__table__.c.company_id, JournalAction.__table__.c.id],
            name="fk_company_execution_waiting_action",
        ),
        UniqueConstraint("company_id", "run_id", name="uq_company_execution_run"),
        UniqueConstraint("company_id", "task_id", "run_id", name="uq_company_execution_task_run"),
        CheckConstraint(
            "fence >= 0 AND segment_number >= 0", name="ck_company_execution_generations"
        ),
        CheckConstraint(
            "state IN ('eligible','running','awaiting_approval',"
            "'outcome_unknown','verifying','blocked')",
            name="ck_company_execution_state",
        ),
        CheckConstraint(
            "(worker_id IS NULL AND lease_until IS NULL AND lease_mode IS NULL "
            "AND lease_principal_id IS NULL) OR "
            "(worker_id IS NOT NULL AND lease_until IS NOT NULL "
            "AND lease_principal_id IS NOT NULL AND lease_mode IN ('execute','reconcile'))",
            name="ck_company_execution_lease",
        ),
        *(
            CheckConstraint(
                f"{kind}_limit BETWEEN 0 AND {maximum} AND {kind}_used >= 0 AND "
                f"{kind}_delegated >= 0 AND {kind}_used + {kind}_delegated <= {kind}_limit",
                name=f"ck_company_execution_{kind}",
            )
            for kind, maximum in (
                ("model_requests", 12),
                ("tool_attempts", 20),
                ("rework_rounds", 2),
                ("plan_revisions", 2),
            )
        ),
    )


class ExecutionAttempt(ExecutionBase):
    """Immutable same-kind logical attempt reservation; failure does not refund it."""

    __tablename__ = "company_execution_attempts"
    company_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    attempt_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    trace_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(24))
    fence: Mapped[int] = mapped_column(BigInteger)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "task_id"],
            ["company_execution_work.company_id", "company_execution_work.task_id"],
            name="fk_company_execution_attempt_work",
        ),
        CheckConstraint(
            "kind IN ('model_requests','tool_attempts','rework_rounds','plan_revisions') "
            "AND fence > 0",
            name="ck_company_execution_attempt_kind",
        ),
    )


class EffectIntent(ExecutionBase):
    """An exact application intent; external receivers still need idempotency/reconciliation."""

    __tablename__ = "company_effect_intents"
    company_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    action_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    trace_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    proposal_hash: Mapped[str] = mapped_column(String(64))
    intent_fence: Mapped[int] = mapped_column(BigInteger)
    attempt_kind: Mapped[str] = mapped_column(String(24))
    state: Mapped[str] = mapped_column(String(24), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    receipt_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "action_id",
            "task_id",
            "trace_id",
            "run_id",
            "intent_fence",
            "attempt_kind",
            "proposal_hash",
            name="uq_company_notification_intent",
        ),
        ForeignKeyConstraint(
            ["company_id", "action_id"],
            [JournalAction.__table__.c.company_id, JournalAction.__table__.c.id],
            name="fk_company_effect_registered_action",
        ),
        ForeignKeyConstraint(
            ["company_id", "task_id", "run_id"],
            [
                "company_execution_work.company_id",
                "company_execution_work.task_id",
                "company_execution_work.run_id",
            ],
            name="fk_company_effect_execution",
        ),
        CheckConstraint(
            "intent_fence > 0 AND state IN ('intent','outcome_unknown','succeeded','failed')",
            name="ck_company_effect_state",
        ),
        CheckConstraint(
            "attempt_kind IN ('model_requests','tool_attempts')",
            name="ck_company_effect_attempt_kind",
        ),
    )
