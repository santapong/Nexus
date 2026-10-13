"""Claim history and explicit support; verified-outcome writes remain deliberately disabled."""

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
from nexus.company.directory_models import DirectoryMembership


class BrainClaimRevision(CompanyRow, BrainBase):
    __tablename__ = "company_brain_claim_revisions"
    claim_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(Uuid)
    resource_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    source_event_json: Mapped[str] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    validity_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validity_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    origin: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(16))
    verification_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    receipt_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    __table_args__ = (
        UniqueConstraint("company_id", "claim_id", "revision", name="uq_brain_claim_revision"),
        UniqueConstraint(
            "company_id", "claim_id", "claim_revision_id", name="uq_brain_claim_revision_scope"
        ),
        ForeignKeyConstraint(
            ["company_id", "resource_id"],
            ["company_brain_resources.company_id", "company_brain_resources.resource_id"],
            name="fk_brain_claim_resource",
        ),
        CheckConstraint(
            "kind IN ('observation','decision','hypothesis','plan','commitment','verifie"
            "d_outcome')",
            name="ck_brain_claim_kind",
        ),
        CheckConstraint(
            "kind <> 'verified_outcome'", name="ck_company_brain_verified_outcome_disabled"
        ),
        CheckConstraint(
            "verification_id IS NULL AND receipt_id IS NULL",
            name="ck_brain_claim_no_uuid_promotion",
        ),
        CheckConstraint("octet_length(text) BETWEEN 1 AND 8192", name="ck_brain_claim_text_bytes"),
        CheckConstraint(
            "status IN ('proposed','source_report','superseded') AND origin IN ('operato"
            "r','source','model','trusted_publisher') AND (origin <> 'model' OR status ="
            " 'proposed')",
            name="ck_brain_claim_origin",
        ),
        CheckConstraint(
            "validity_start IS NULL OR validity_end IS NULL OR validity_end > validity_start",
            name="ck_brain_claim_validity",
        ),
    )


class BrainClaimHead(CompanyRow, BrainBase):
    __tablename__ = "company_brain_claim_heads"
    claim_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    current_revision_id: Mapped[UUID] = mapped_column(Uuid)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "claim_id", "current_revision_id"],
            [
                "company_brain_claim_revisions.company_id",
                "company_brain_claim_revisions.claim_id",
                "company_brain_claim_revisions.claim_revision_id",
            ],
            name="fk_brain_claim_head_revision",
        ),
    )


class BrainClaimEvidence(CompanyRow, BrainBase):
    __tablename__ = "company_brain_claim_evidence"
    claim_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    evidence_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    relationship: Mapped[str] = mapped_column(String(12), primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "claim_revision_id"],
            [
                "company_brain_claim_revisions.company_id",
                "company_brain_claim_revisions.claim_revision_id",
            ],
            name="fk_brain_claim_evidence_revision",
        ),
        ForeignKeyConstraint(
            ["company_id", "evidence_id"],
            ["company_brain_evidence.company_id", "company_brain_evidence.evidence_id"],
            name="fk_brain_claim_evidence_source",
        ),
        CheckConstraint(
            "relationship IN ('supports','challenges')", name="ck_brain_claim_evidence_relation"
        ),
    )


class BrainClaimLink(CompanyRow, RecordedRow, BrainBase):
    __tablename__ = "company_brain_claim_links"
    link_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    subject_revision_id: Mapped[UUID] = mapped_column(Uuid)
    object_revision_id: Mapped[UUID] = mapped_column(Uuid)
    predicate: Mapped[str] = mapped_column(String(16))
    rationale: Mapped[str] = mapped_column(String(500))
    recorded_by: Mapped[UUID] = mapped_column(Uuid)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "subject_revision_id"],
            [
                "company_brain_claim_revisions.company_id",
                "company_brain_claim_revisions.claim_revision_id",
            ],
            name="fk_brain_claim_link_subject",
        ),
        ForeignKeyConstraint(
            ["company_id", "object_revision_id"],
            [
                "company_brain_claim_revisions.company_id",
                "company_brain_claim_revisions.claim_revision_id",
            ],
            name="fk_brain_claim_link_object",
        ),
        ForeignKeyConstraint(
            ["company_id", "recorded_by"],
            [
                DirectoryMembership.__table__.c.company_id,
                DirectoryMembership.__table__.c.principal_id,
            ],
            name="fk_brain_claim_link_author",
        ),
        CheckConstraint(
            "predicate IN ('conflicts_with','supersedes') AND subject_revision_id <> obj"
            "ect_revision_id",
            name="ck_brain_claim_link_relation",
        ),
    )


class BrainClaimLinkEvidence(CompanyRow, BrainBase):
    __tablename__ = "company_brain_claim_link_evidence"
    link_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    evidence_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "link_id"],
            ["company_brain_claim_links.company_id", "company_brain_claim_links.link_id"],
            name="fk_brain_claim_link_evidence_link",
        ),
        ForeignKeyConstraint(
            ["company_id", "evidence_id"],
            ["company_brain_evidence.company_id", "company_brain_evidence.evidence_id"],
            name="fk_brain_claim_link_evidence_source",
        ),
    )
