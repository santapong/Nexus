"""Permanent action-to-segment scheduling identity, separate from DBOS queue retention."""

from uuid import UUID

from sqlalchemy import ForeignKeyConstraint, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import JournalAction


class DispatchBase(DeclarativeBase):
    """Dedicated scheduling history metadata for company c005."""


class SegmentDispatch(DispatchBase):
    """One immutable execution segment binding for each consumed exact action."""

    __tablename__ = "company_segment_dispatch"
    company_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    action_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    segment_id: Mapped[UUID] = mapped_column(Uuid)
    workflow_id: Mapped[str] = mapped_column(String(64), unique=True)
    binding_json: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "action_id"],
            [JournalAction.__table__.c.company_id, JournalAction.__table__.c.id],
            name="fk_company_dispatch_action",
        ),
        ForeignKeyConstraint(
            ["company_id", "task_id", "run_id"],
            [
                ExecutionWork.__table__.c.company_id,
                ExecutionWork.__table__.c.task_id,
                ExecutionWork.__table__.c.run_id,
            ],
            name="fk_company_dispatch_run",
        ),
        UniqueConstraint("company_id", "segment_id", name="uq_company_dispatch_segment"),
    )
