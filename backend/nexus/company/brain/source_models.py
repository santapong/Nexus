"""Uninstalled immutable UTF-8 source metadata; native revision FKs remain company-bound."""

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
from sqlalchemy.orm import Mapped, mapped_column

from nexus.company.brain.model_base import BrainBase, CompanyRow, RecordedRow
from nexus.company.directory_models import DirectoryMembership


class BrainArtifactRevision(CompanyRow, RecordedRow, BrainBase):
    __tablename__ = "company_brain_artifact_revisions"
    artifact_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    artifact_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[str] = mapped_column(String(500))
    resource_id: Mapped[UUID] = mapped_column(Uuid)
    media_type: Mapped[str] = mapped_column(String(32))
    storage_symbol: Mapped[str] = mapped_column(String(128))
    raw_text: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    byte_length: Mapped[int] = mapped_column(Integer)
    derivation_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    __table_args__ = (
        UniqueConstraint(
            "company_id", "artifact_id", "revision", name="uq_brain_artifact_revision"
        ),
        ForeignKeyConstraint(
            ["company_id", "resource_id"],
            ["company_brain_resources.company_id", "company_brain_resources.resource_id"],
            name="fk_brain_artifact_resource",
        ),
        ForeignKeyConstraint(
            ["company_id", "derivation_id"],
            ["company_brain_derivations.company_id", "company_brain_derivations.derivation_id"],
            name="fk_brain_artifact_derivation",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "byte_length = octet_length(raw_text) AND byte_length BETWEEN 1 AND 2097152",
            name="ck_brain_artifact_bytes",
        ),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_brain_artifact_hash"),
        CheckConstraint(
            "media_type IN ('text/plain','text/markdown','application/json')",
            name="ck_brain_artifact_media",
        ),
    )


class BrainSource(CompanyRow, RecordedRow, BrainBase):
    __tablename__ = "company_brain_sources"
    source_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    resource_id: Mapped[UUID] = mapped_column(Uuid)
    source_symbol: Mapped[str] = mapped_column(String(128))
    external_key: Mapped[str] = mapped_column(String(500))
    authority_profile: Mapped[str] = mapped_column(String(128))
    data_classification: Mapped[str] = mapped_column(String(16))
    recorded_by: Mapped[UUID] = mapped_column(Uuid)
    __table_args__ = (
        UniqueConstraint(
            "company_id", "source_symbol", "external_key", name="uq_brain_source_identity"
        ),
        ForeignKeyConstraint(
            ["company_id", "resource_id"],
            ["company_brain_resources.company_id", "company_brain_resources.resource_id"],
            name="fk_brain_source_resource",
        ),
        ForeignKeyConstraint(
            ["company_id", "recorded_by"],
            [
                DirectoryMembership.__table__.c.company_id,
                DirectoryMembership.__table__.c.principal_id,
            ],
            name="fk_brain_source_author",
        ),
        CheckConstraint(
            "data_classification IN ('public','internal','confidential','restricted')",
            name="ck_brain_source_classification",
        ),
    )


class BrainSourceRevision(CompanyRow, BrainBase):
    __tablename__ = "company_brain_source_revisions"
    source_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[str] = mapped_column(String(500))
    artifact_revision_id: Mapped[UUID] = mapped_column(Uuid)
    source_event_precision: Mapped[str] = mapped_column(String(8))
    source_event_value: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_event_basis: Mapped[str] = mapped_column(String(200))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_by: Mapped[UUID] = mapped_column(Uuid)
    source_author: Mapped[str | None] = mapped_column(String(500), nullable=True)
    derivation_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    __table_args__ = (
        UniqueConstraint("company_id", "source_id", "revision", name="uq_brain_source_revision"),
        UniqueConstraint(
            "company_id", "source_id", "source_revision_id", name="uq_brain_source_revision_scope"
        ),
        UniqueConstraint(
            "company_id",
            "source_revision_id",
            "artifact_revision_id",
            name="uq_brain_source_artifact_scope",
        ),
        ForeignKeyConstraint(
            ["company_id", "source_id"],
            ["company_brain_sources.company_id", "company_brain_sources.source_id"],
            name="fk_brain_revision_source",
        ),
        ForeignKeyConstraint(
            ["company_id", "artifact_revision_id"],
            [
                "company_brain_artifact_revisions.company_id",
                "company_brain_artifact_revisions.artifact_revision_id",
            ],
            name="fk_brain_revision_artifact",
        ),
        ForeignKeyConstraint(
            ["company_id", "recorded_by"],
            [
                DirectoryMembership.__table__.c.company_id,
                DirectoryMembership.__table__.c.principal_id,
            ],
            name="fk_brain_revision_author",
        ),
        ForeignKeyConstraint(
            ["company_id", "derivation_id"],
            ["company_brain_derivations.company_id", "company_brain_derivations.derivation_id"],
            name="fk_brain_revision_derivation",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "source_event_precision IN ('unknown','year','month','day','instant') AND (("
            "source_event_precision = 'unknown') = (source_event_value IS NULL))",
            name="ck_brain_source_event_precision",
        ),
    )


class BrainSourceHead(CompanyRow, BrainBase):
    __tablename__ = "company_brain_source_heads"
    source_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    current_revision_id: Mapped[UUID] = mapped_column(Uuid)
    generation: Mapped[int] = mapped_column(BigInteger)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fresh_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    availability: Mapped[str] = mapped_column(String(16))
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "source_id", "current_revision_id"],
            [
                "company_brain_source_revisions.company_id",
                "company_brain_source_revisions.source_id",
                "company_brain_source_revisions.source_revision_id",
            ],
            name="fk_brain_source_head_revision",
        ),
        CheckConstraint("generation >= 1", name="ck_brain_source_head_generation"),
        CheckConstraint(
            "fresh_until IS NULL OR fresh_until > observed_at", name="ck_brain_source_freshness"
        ),
        CheckConstraint(
            "availability IN ('available','quarantined','unavailable')",
            name="ck_brain_source_availability",
        ),
    )
