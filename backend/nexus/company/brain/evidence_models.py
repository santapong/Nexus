"""Exact raw artifact citations and separate parser offsets; no inferred provenance edges."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from nexus.company.brain.model_base import BrainBase, CompanyRow, RecordedRow


class BrainParseRevision(CompanyRow, RecordedRow, BrainBase):
    __tablename__ = "company_brain_parse_revisions"
    parse_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_revision_id: Mapped[UUID] = mapped_column(Uuid)
    parser_version: Mapped[str] = mapped_column(String(128))
    chunker_version: Mapped[str] = mapped_column(String(128))
    canonical_text: Mapped[str] = mapped_column(Text)
    canonical_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "source_revision_id",
            "parser_version",
            "chunker_version",
            name="uq_brain_parse_recipe",
        ),
        UniqueConstraint(
            "company_id",
            "parse_revision_id",
            "source_revision_id",
            name="uq_brain_parse_source_scope",
        ),
        ForeignKeyConstraint(
            ["company_id", "source_revision_id"],
            [
                "company_brain_source_revisions.company_id",
                "company_brain_source_revisions.source_revision_id",
            ],
            name="fk_brain_parse_source",
        ),
        CheckConstraint(
            "octet_length(canonical_text) BETWEEN 1 AND 1048576", name="ck_brain_parse_bytes"
        ),
        CheckConstraint("canonical_sha256 ~ '^[0-9a-f]{64}$'", name="ck_brain_parse_hash"),
    )


class BrainParseFailure(CompanyRow, RecordedRow, BrainBase):
    __tablename__ = "company_brain_parse_failures"
    failure_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_id: Mapped[UUID] = mapped_column(Uuid)
    source_revision_id: Mapped[UUID] = mapped_column(Uuid)
    parser_version: Mapped[str] = mapped_column(String(128))
    chunker_version: Mapped[str] = mapped_column(String(128))
    reason_code: Mapped[str] = mapped_column(String(24))
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "source_revision_id",
            "parser_version",
            "chunker_version",
            name="uq_brain_parse_failure_recipe",
        ),
        ForeignKeyConstraint(
            ["company_id", "source_id", "source_revision_id"],
            [
                "company_brain_source_revisions.company_id",
                "company_brain_source_revisions.source_id",
                "company_brain_source_revisions.source_revision_id",
            ],
            name="fk_brain_parse_failure_source",
        ),
        CheckConstraint(
            "reason_code IN ('unsupported_media','unsupported_recipe','invalid_utf8',"
            "'invalid_json','source_too_large','parsed_too_large','chunk_limit',"
            "'parse_timeout','parse_failed')",
            name="ck_brain_parse_failure_reason",
        ),
    )


class BrainChunk(CompanyRow, BrainBase):
    __tablename__ = "company_brain_chunks"
    chunk_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    parse_revision_id: Mapped[UUID] = mapped_column(Uuid)
    source_revision_id: Mapped[UUID] = mapped_column(Uuid)
    ordinal: Mapped[int] = mapped_column(Integer)
    start_byte: Mapped[int] = mapped_column(Integer)
    end_byte: Mapped[int] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(500), nullable=True)
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    search_config: Mapped[str] = mapped_column(String(16))
    search_vector: Mapped[str] = mapped_column(TSVECTOR)
    __table_args__ = (
        UniqueConstraint(
            "company_id", "parse_revision_id", "ordinal", name="uq_brain_chunk_ordinal"
        ),
        UniqueConstraint(
            "company_id",
            "chunk_id",
            "parse_revision_id",
            "source_revision_id",
            name="uq_brain_chunk_parse_scope",
        ),
        ForeignKeyConstraint(
            ["company_id", "parse_revision_id", "source_revision_id"],
            [
                "company_brain_parse_revisions.company_id",
                "company_brain_parse_revisions.parse_revision_id",
                "company_brain_parse_revisions.source_revision_id",
            ],
            name="fk_brain_chunk_parse",
        ),
        CheckConstraint(
            "ordinal BETWEEN 0 AND 255 AND start_byte >= 0 AND end_byte > start_byte AND"
            " end_byte - start_byte = octet_length(text) AND octet_length(text) <= 8192",
            name="ck_brain_chunk_span",
        ),
        CheckConstraint(
            "search_config IN ('simple','english')", name="ck_brain_chunk_search_config"
        ),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_brain_chunk_hash"),
        Index("ix_brain_chunk_search", "search_vector", postgresql_using="gin"),
    )


class BrainEvidence(CompanyRow, BrainBase):
    __tablename__ = "company_brain_evidence"
    evidence_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_id: Mapped[UUID] = mapped_column(Uuid)
    source_revision_id: Mapped[UUID] = mapped_column(Uuid)
    artifact_revision_id: Mapped[UUID] = mapped_column(Uuid)
    raw_start_byte: Mapped[int] = mapped_column(Integer)
    raw_end_byte: Mapped[int] = mapped_column(Integer)
    raw_section: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    span_sha256: Mapped[str] = mapped_column(String(64))
    parse_revision_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    parsed_start_byte: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parsed_end_byte: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "source_id", "source_revision_id"],
            [
                "company_brain_source_revisions.company_id",
                "company_brain_source_revisions.source_id",
                "company_brain_source_revisions.source_revision_id",
            ],
            name="fk_brain_evidence_source",
        ),
        ForeignKeyConstraint(
            ["company_id", "source_revision_id", "artifact_revision_id"],
            [
                "company_brain_source_revisions.company_id",
                "company_brain_source_revisions.source_revision_id",
                "company_brain_source_revisions.artifact_revision_id",
            ],
            name="fk_brain_evidence_artifact",
        ),
        ForeignKeyConstraint(
            ["company_id", "parse_revision_id", "source_revision_id"],
            [
                "company_brain_parse_revisions.company_id",
                "company_brain_parse_revisions.parse_revision_id",
                "company_brain_parse_revisions.source_revision_id",
            ],
            name="fk_brain_evidence_parse",
        ),
        ForeignKeyConstraint(
            ["company_id", "chunk_id", "parse_revision_id", "source_revision_id"],
            [
                "company_brain_chunks.company_id",
                "company_brain_chunks.chunk_id",
                "company_brain_chunks.parse_revision_id",
                "company_brain_chunks.source_revision_id",
            ],
            name="fk_brain_evidence_chunk",
        ),
        CheckConstraint(
            "raw_start_byte >= 0 AND raw_end_byte > raw_start_byte AND raw_end_byte - ra"
            "w_start_byte <= 16384",
            name="ck_brain_evidence_raw_span",
        ),
        CheckConstraint(
            "(parse_revision_id IS NULL AND parsed_start_byte IS NULL AND parsed_end_byt"
            "e IS NULL AND chunk_id IS NULL) OR (parse_revision_id IS NOT NULL AND "
            "parsed_start_byte IS NOT NULL AND parsed_end_byte IS NOT NULL AND "
            "parsed_start_byte >= 0 AND parsed_end_byte > parsed_start_byte AND parsed_end_by"
            "te - parsed_start_byte <= 16384)",
            name="ck_brain_evidence_parsed_span",
        ),
        CheckConstraint("span_sha256 ~ '^[0-9a-f]{64}$'", name="ck_brain_evidence_hash"),
    )
