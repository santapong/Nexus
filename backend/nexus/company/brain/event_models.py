"""Company-scoped event sequencing and cursor state; no raw document/credential payload."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.company.brain.model_base import BrainBase, CompanyRow, RecordedRow
from nexus.harness.journal_models import JournalAction


class BrainEvent(CompanyRow, RecordedRow, BrainBase):
    __tablename__ = "company_brain_events"
    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(24))
    resource_id: Mapped[UUID] = mapped_column(Uuid)
    deduplication_key: Mapped[str] = mapped_column(String(128))
    operation_id: Mapped[UUID] = mapped_column(Uuid)
    trace_id: Mapped[UUID] = mapped_column(Uuid)
    source_revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    resource_generation: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    __table_args__ = (
        UniqueConstraint("company_id", "sequence", name="uq_brain_event_sequence"),
        UniqueConstraint("company_id", "deduplication_key", name="uq_brain_event_deduplication"),
        ForeignKeyConstraint(
            ["company_id", "resource_id"],
            ["company_brain_resources.company_id", "company_brain_resources.resource_id"],
            name="fk_brain_event_resource",
        ),
        ForeignKeyConstraint(
            ["company_id", "source_revision_id"],
            [
                "company_brain_source_revisions.company_id",
                "company_brain_source_revisions.source_revision_id",
            ],
            name="fk_brain_event_source",
        ),
        ForeignKeyConstraint(
            ["company_id", "action_id"],
            [JournalAction.__table__.c.company_id, JournalAction.__table__.c.id],
            name="fk_brain_event_action",
        ),
        CheckConstraint(
            "sequence >= 1 AND (resource_generation IS NULL OR resource_generation >= 1)",
            name="ck_brain_event_sequence",
        ),
        CheckConstraint(
            "kind IN ('source_revised','acl_changed','claims_changed','derivation_change"
            "d','receipt_recorded','verification_recorded')",
            name="ck_brain_event_kind",
        ),
        CheckConstraint(
            "(kind <> 'source_revised' OR source_revision_id IS NOT NULL) AND (kind <> '"
            "acl_changed' OR resource_generation IS NOT NULL) AND (kind NOT IN ('receipt"
            "_recorded','verification_recorded') OR action_id IS NOT NULL)",
            name="ck_brain_event_binding",
        ),
    )


class BrainEventCursor(CompanyRow, BrainBase):
    __tablename__ = "company_brain_event_cursors"
    consumer: Mapped[str] = mapped_column(String(128), primary_key=True)
    recipe_version: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (CheckConstraint("last_sequence >= 0", name="ck_brain_event_cursor"),)
