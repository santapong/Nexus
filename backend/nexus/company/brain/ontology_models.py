"""Native typed ontology identities and immutable revisions; no execution state fields."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from nexus.company.brain.model_base import BrainBase, CompanyRow, RecordedRow
from nexus.company.brain.relationships import ENDPOINTS

KINDS_SQL = (
    "'Company','Department','Principal','Product','Project','Goal','WorkItem','C"
    "ustomer','SupportCase','Decision','Commitment','Evidence','Artifact','Actio"
    "n','Verification','Budget','AuthorityPolicy'"
)
ENDPOINT_SQL = " OR ".join(
    f"(predicate = '{predicate}' AND subject_kind = '{subject}' AND object_kind = '{object_}')"
    for predicate, pairs in sorted(ENDPOINTS.items())
    for subject, object_ in sorted(pairs)
)


class BrainEntity(CompanyRow, RecordedRow, BrainBase):
    __tablename__ = "company_brain_entities"
    entity_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    resource_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(20))
    current_revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    __table_args__ = (
        UniqueConstraint("company_id", "entity_id", "kind", name="uq_brain_entity_kind"),
        ForeignKeyConstraint(
            ["company_id", "resource_id"],
            ["company_brain_resources.company_id", "company_brain_resources.resource_id"],
            name="fk_brain_entity_resource",
        ),
        ForeignKeyConstraint(
            ["company_id", "entity_id", "current_revision_id", "kind"],
            [
                "company_brain_entity_revisions.company_id",
                "company_brain_entity_revisions.entity_id",
                "company_brain_entity_revisions.entity_revision_id",
                "company_brain_entity_revisions.kind",
            ],
            name="fk_brain_entity_current",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(f"kind IN ({KINDS_SQL})", name="ck_brain_entity_kind"),
    )


class BrainEntityRevision(CompanyRow, BrainBase):
    __tablename__ = "company_brain_entity_revisions"
    entity_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    entity_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(20))
    revision: Mapped[str] = mapped_column(String(500))
    content_json: Mapped[str] = mapped_column(Text)
    source_event_json: Mapped[str] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    validity_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validity_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    origin: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    __table_args__ = (
        UniqueConstraint("company_id", "entity_id", "revision", name="uq_brain_entity_revision"),
        UniqueConstraint(
            "company_id",
            "entity_id",
            "entity_revision_id",
            "kind",
            name="uq_brain_entity_revision_scope",
        ),
        ForeignKeyConstraint(
            ["company_id", "entity_id", "kind"],
            [
                "company_brain_entities.company_id",
                "company_brain_entities.entity_id",
                "company_brain_entities.kind",
            ],
            name="fk_brain_entity_revision_identity",
        ),
        CheckConstraint(
            "status IN ('proposed','source_report') AND origin IN ('operator','source','"
            "model') AND (origin <> 'model' OR status = 'proposed')",
            name="ck_brain_entity_origin",
        ),
        CheckConstraint(
            "octet_length(content_json) <= 32768", name="ck_brain_entity_content_bytes"
        ),
        CheckConstraint(
            "validity_start IS NULL OR validity_end IS NULL OR validity_end > validity_start",
            name="ck_brain_entity_validity",
        ),
    )


class BrainEntityEvidence(CompanyRow, BrainBase):
    __tablename__ = "company_brain_entity_evidence"
    entity_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    evidence_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "entity_revision_id"],
            [
                "company_brain_entity_revisions.company_id",
                "company_brain_entity_revisions.entity_revision_id",
            ],
            name="fk_brain_entity_evidence_revision",
        ),
        ForeignKeyConstraint(
            ["company_id", "evidence_id"],
            ["company_brain_evidence.company_id", "company_brain_evidence.evidence_id"],
            name="fk_brain_entity_evidence_source",
        ),
    )


class BrainRelationshipRevision(CompanyRow, RecordedRow, BrainBase):
    __tablename__ = "company_brain_relationship_revisions"
    relationship_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    relationship_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[str] = mapped_column(String(500))
    predicate: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[UUID] = mapped_column(Uuid)
    subject_revision_id: Mapped[UUID] = mapped_column(Uuid)
    subject_kind: Mapped[str] = mapped_column(String(20))
    object_id: Mapped[UUID] = mapped_column(Uuid)
    object_revision_id: Mapped[UUID] = mapped_column(Uuid)
    object_kind: Mapped[str] = mapped_column(String(20))
    validity_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validity_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    origin: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    __table_args__ = (
        UniqueConstraint(
            "company_id", "relationship_id", "revision", name="uq_brain_relationship_revision"
        ),
        ForeignKeyConstraint(
            ["company_id", "subject_id", "subject_revision_id", "subject_kind"],
            [
                "company_brain_entity_revisions.company_id",
                "company_brain_entity_revisions.entity_id",
                "company_brain_entity_revisions.entity_revision_id",
                "company_brain_entity_revisions.kind",
            ],
            name="fk_brain_relationship_subject",
        ),
        ForeignKeyConstraint(
            ["company_id", "object_id", "object_revision_id", "object_kind"],
            [
                "company_brain_entity_revisions.company_id",
                "company_brain_entity_revisions.entity_id",
                "company_brain_entity_revisions.entity_revision_id",
                "company_brain_entity_revisions.kind",
            ],
            name="fk_brain_relationship_object",
        ),
        CheckConstraint(ENDPOINT_SQL, name="ck_brain_relationship_endpoints"),
        CheckConstraint(
            "subject_revision_id <> object_revision_id", name="ck_brain_relationship_not_self"
        ),
        CheckConstraint(
            "status IN ('proposed','source_report') AND origin IN ('operator','source','"
            "model') AND (origin <> 'model' OR status = 'proposed')",
            name="ck_brain_relationship_origin",
        ),
        CheckConstraint(
            "validity_start IS NULL OR validity_end IS NULL OR validity_end > validity_start",
            name="ck_brain_relationship_validity",
        ),
    )


class BrainRelationshipEvidence(CompanyRow, BrainBase):
    __tablename__ = "company_brain_relationship_evidence"
    relationship_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    evidence_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "relationship_revision_id"],
            [
                "company_brain_relationship_revisions.company_id",
                "company_brain_relationship_revisions.relationship_revision_id",
            ],
            name="fk_brain_relationship_evidence_revision",
        ),
        ForeignKeyConstraint(
            ["company_id", "evidence_id"],
            ["company_brain_evidence.company_id", "company_brain_evidence.evidence_id"],
            name="fk_brain_relationship_evidence_source",
        ),
    )
