"""Immutable source/artifact revisions and raw-byte citations, independent of authority."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import (
    SHA256,
    BrainContract,
    Count,
    Name,
    Ordinal,
    SourceTime,
    Symbol,
    ValueContract,
    require_company,
)
from nexus.core.llm.company_registry import DataClassification


class UTF8Span(ValueContract):
    start_byte: Ordinal
    end_byte: Count
    section: Name | None = None
    path: Name | None = None
    page: Count | None = None

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if not 0 < self.end_byte - self.start_byte <= 16_384:
            raise ValueError("Evidence span must contain at most 16 KiB")
        if self.path and (self.path.startswith(("/", "\\")) or ".." in self.path.split("/")):
            raise ValueError("A citation path must be an addressable relative locator")
        return self


class ArtifactRevisionRef(BrainContract):
    artifact_id: UUID
    artifact_revision_id: UUID
    revision: Name
    sha256: SHA256
    byte_length: Annotated[Count, Field(le=2_097_152)]


class ArtifactRevisionRecord(ArtifactRevisionRef):
    resource: ResourceRef
    media_type: Literal["text/plain", "text/markdown", "text/html", "application/json"]
    storage_symbol: Symbol
    raw_text: Annotated[str, StringConstraints(min_length=1, max_length=2_097_152)]
    recorded_at: AwareDatetime
    derivation_id: UUID | None = None

    @model_validator(mode="after")
    def actual_bytes(self) -> Self:
        require_company(self.company_id, self.resource)
        if self.media_type == "text/html" and self.derivation_id is None:
            raise ValueError("HTML artifact requires its immutable derivation identity")
        raw = self.raw_text.encode("utf-8")
        if (
            "\x00" in self.raw_text
            or len(raw) != self.byte_length
            or hashlib.sha256(raw).hexdigest() != self.sha256
        ):
            raise ValueError("Artifact hash/length must bind exact supported UTF-8 bytes")
        return self


class SourceRevisionRef(BrainContract):
    source_id: UUID
    source_revision_id: UUID
    revision: Name


class SourceRegistration(BrainContract):
    """Trusted operator registration; registered symbol grants no caller URL/credentials."""

    source_id: UUID
    resource: ResourceRef
    source_symbol: Symbol
    external_key: Name

    @model_validator(mode="after")
    def registered_location(self) -> Self:
        require_company(self.company_id, self.resource)
        if (
            "://" in self.external_key
            or self.external_key.startswith(("/", "\\"))
            or ".." in self.external_key.split("/")
        ):
            raise ValueError("Source identity cannot be an arbitrary URL/filesystem path")
        return self


class SourceRecord(SourceRegistration):
    authority_profile: Symbol
    data_classification: DataClassification
    recorded_by: UUID
    recorded_at: AwareDatetime


class SourceRevisionRecord(SourceRevisionRef):
    artifact: ArtifactRevisionRef
    source_event: SourceTime
    ingested_at: AwareDatetime
    recorded_by: UUID
    source_author: Name | None = None
    derivation_id: UUID | None = None

    @model_validator(mode="after")
    def same_artifact(self) -> Self:
        require_company(self.company_id, self.artifact)
        return self


class SourceHead(BrainContract):
    source_id: UUID
    current: SourceRevisionRef
    generation: Count
    observed_at: AwareDatetime
    fresh_until: AwareDatetime | None = None
    availability: Literal["available", "quarantined", "unavailable"]

    @model_validator(mode="after")
    def current_source(self) -> Self:
        require_company(self.company_id, self.current)
        if self.current.source_id != self.source_id:
            raise ValueError("Current pointer refers to another logical source")
        if self.fresh_until and self.fresh_until <= self.observed_at:
            raise ValueError("Source freshness interval must be positive")
        return self


class IngestCommand(BrainContract):
    source_id: UUID
    revision: Name
    artifact: ArtifactRevisionRef
    expected_previous_revision_id: UUID | None = None
    parser_version: Symbol = "utf8-identity-v1"
    chunker_version: Symbol = "utf8-sections-v1"

    @model_validator(mode="after")
    def same_artifact(self) -> Self:
        require_company(self.company_id, self.artifact)
        return self


class IngestReceipt(BrainContract):
    status: Literal["accepted", "quarantined", "conflict"]
    source: SourceRevisionRef
    artifact: ArtifactRevisionRef
    parser_version: Symbol
    chunker_version: Symbol
    reason_code: Symbol | None = None

    @model_validator(mode="after")
    def references(self) -> Self:
        require_company(self.company_id, self.source, self.artifact)
        return self


class ParseRevisionRecord(BrainContract):
    parse_revision_id: UUID
    source: SourceRevisionRef
    parser_version: Symbol
    chunker_version: Symbol
    canonical_text: Annotated[str, StringConstraints(min_length=1, max_length=1_048_576)]
    canonical_sha256: SHA256
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def actual_text(self) -> Self:
        require_company(self.company_id, self.source)
        raw = self.canonical_text.encode()
        if len(raw) > 1_048_576 or hashlib.sha256(raw).hexdigest() != self.canonical_sha256:
            raise ValueError("Parsed content exceeds its bound or hash")
        return self


class ParseFailureRecord(BrainContract):
    """Immutable sanitized failure for one exact source/parser/chunker recipe."""

    failure_id: UUID
    source: SourceRevisionRef
    parser_version: Symbol
    chunker_version: Symbol
    reason_code: Literal[
        "unsupported_media",
        "unsupported_recipe",
        "invalid_utf8",
        "invalid_json",
        "source_too_large",
        "parsed_too_large",
        "chunk_limit",
        "parse_timeout",
        "parse_failed",
    ]
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def same_source(self) -> Self:
        require_company(self.company_id, self.source)
        return self


class SourceChunkRecord(BrainContract):
    chunk_id: UUID
    parse_revision_id: UUID
    source: SourceRevisionRef
    ordinal: Annotated[Ordinal, Field(le=255)]
    parsed_span: UTF8Span
    text: Annotated[str, StringConstraints(min_length=1, max_length=8192)]
    sha256: SHA256

    @model_validator(mode="after")
    def actual_chunk(self) -> Self:
        require_company(self.company_id, self.source)
        raw = self.text.encode()
        if (
            len(raw) > 8192
            or len(raw) != self.parsed_span.end_byte - self.parsed_span.start_byte
            or hashlib.sha256(raw).hexdigest() != self.sha256
        ):
            raise ValueError("Chunk text/UTF8 span/hash disagree")
        return self


class EvidenceRef(BrainContract):
    evidence_id: UUID


class EvidenceRecord(EvidenceRef):
    """Raw locator is mandatory; a changed parser must separately map its parsed span."""

    source: SourceRevisionRef
    artifact: ArtifactRevisionRef
    raw_span: UTF8Span
    span_sha256: SHA256
    source_event: SourceTime
    ingested_at: AwareDatetime
    parse_revision_id: UUID | None = None
    parsed_span: UTF8Span | None = None
    chunk_id: UUID | None = None

    @model_validator(mode="after")
    def exact_references(self) -> Self:
        require_company(self.company_id, self.source, self.artifact)
        if self.raw_span.end_byte > self.artifact.byte_length:
            raise ValueError("Raw evidence locator escapes its exact artifact")
        if (self.parse_revision_id is None) != (self.parsed_span is None):
            raise ValueError("Parsed locator and revision must travel together")
        if self.chunk_id is not None and self.parse_revision_id is None:
            raise ValueError("Chunk evidence requires its exact parse revision")
        return self
