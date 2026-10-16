"""Explicit source/evidence contributors bind summaries and source-revision derivatives."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from nexus.company.brain.model_base import BrainBase, CompanyRow, RecordedRow


class BrainDerivation(CompanyRow, RecordedRow, BrainBase):
    __tablename__ = "company_brain_derivations"
    derivation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    artifact_revision_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(24))
    recipe_version: Mapped[str] = mapped_column(String(128))
    model_recipe: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "artifact_revision_id"],
            [
                "company_brain_artifact_revisions.company_id",
                "company_brain_artifact_revisions.artifact_revision_id",
            ],
            name="fk_brain_derivation_artifact",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "kind IN ('summary','chart','presentation','context','embedding_derived_text',"
            "'model_origin','code_patch')",
            name="ck_brain_derivation_kind",
        ),
        CheckConstraint(
            "prompt_sha256 IS NULL OR prompt_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_brain_derivation_prompt_hash",
        ),
    )


class BrainDerivationSource(CompanyRow, BrainBase):
    __tablename__ = "company_brain_derivation_sources"
    derivation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "derivation_id"],
            ["company_brain_derivations.company_id", "company_brain_derivations.derivation_id"],
            name="fk_brain_derivation_source_parent",
        ),
        ForeignKeyConstraint(
            ["company_id", "source_revision_id"],
            [
                "company_brain_source_revisions.company_id",
                "company_brain_source_revisions.source_revision_id",
            ],
            name="fk_brain_derivation_source_revision",
        ),
    )


class BrainDerivationEvidence(CompanyRow, BrainBase):
    __tablename__ = "company_brain_derivation_evidence"
    derivation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    evidence_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "derivation_id"],
            ["company_brain_derivations.company_id", "company_brain_derivations.derivation_id"],
            name="fk_brain_derivation_evidence_parent",
        ),
        ForeignKeyConstraint(
            ["company_id", "evidence_id"],
            ["company_brain_evidence.company_id", "company_brain_evidence.evidence_id"],
            name="fk_brain_derivation_evidence_source",
        ),
    )
