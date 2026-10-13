"""Bounded search handles and rechecked raw materialization; relevance is not truth."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.base import (
    BrainContract,
    Count,
    Flag,
    Name,
    Ordinal,
    Symbol,
    ValueContract,
    require_company,
)
from nexus.company.brain.claims import ClaimKind
from nexus.company.brain.sources import EvidenceRecord, EvidenceRef, SourceHead, SourceRevisionRef
from nexus.core.llm.company_registry import DataClassification


class RetrievalLimits(ValueContract):
    max_candidates: Annotated[Count, Field(le=100)] = 100
    max_results: Annotated[Count, Field(le=20)] = 20
    max_hops: Annotated[Ordinal, Field(le=2)] = 2
    max_edges: Annotated[Count, Field(le=200)] = 200


class SearchRequest(BrainContract):
    query: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    explicit_evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=32)
    entity_ids: tuple[UUID, ...] = Field(default=(), max_length=32)
    claim_kinds: tuple[ClaimKind, ...] = Field(default=(), max_length=6)
    include_history: Flag = False

    @model_validator(mode="after")
    def bounded_query(self) -> Self:
        if len(self.query.encode()) > 2000 or not self.query.strip():
            raise ValueError("Search text exceeds its byte bound or is empty")
        if len(set(self.explicit_evidence_ids)) != len(self.explicit_evidence_ids):
            raise ValueError("Explicit evidence selection must be unique")
        return self


RetrievalQuery = SearchRequest


class CitationHandle(EvidenceRef):
    """Opaque exact citation metadata; a handle never authorizes source text retrieval."""

    record: EvidenceRecord
    source_contributors: tuple[SourceRevisionRef, ...] = Field(min_length=1, max_length=32)
    contributors: tuple[ResourceGeneration, ...] = Field(min_length=1, max_length=32)
    source_heads: tuple[SourceHead, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def exact_handle(self) -> Self:
        require_company(
            self.company_id,
            self.record,
            *self.source_contributors,
            *self.contributors,
            *self.source_heads,
        )
        if self.evidence_id != self.record.evidence_id:
            raise ValueError("Citation handle identifies another evidence record")
        if self.record.source.source_revision_id not in {
            r.source_revision_id for r in self.source_contributors
        }:
            raise ValueError("Citation contributors must include the direct source revision")
        if {row.source_id for row in self.source_heads} != {
            row.source_id for row in self.source_contributors
        }:
            raise ValueError("Citation must bind current heads for every source contributor")
        if len({row.source_id for row in self.source_heads}) != len(self.source_heads):
            raise ValueError("Citation current source heads must be unique")
        return self


class RankedHandle(BrainContract):
    handle: CitationHandle
    rank: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
    match_kind: Literal["explicit", "entity", "relationship", "fts"]
    hop: Annotated[Ordinal, Field(le=2)]

    @model_validator(mode="after")
    def same_handle(self) -> Self:
        require_company(self.company_id, self.handle)
        return self


class RetrievalResult(BrainContract):
    query_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    recipe_version: Symbol = "brain-retrieval-v1"
    handles: tuple[RankedHandle, ...] = Field(default=(), max_length=100)
    truncated: Flag

    @model_validator(mode="after")
    def same_results(self) -> Self:
        require_company(self.company_id, *self.handles)
        return self


class MaterializedEvidence(BrainContract):
    """Current locked ACL and byte/hash checks precede construction of this record."""

    record: EvidenceRecord
    text: Annotated[str, StringConstraints(min_length=1, max_length=16384)]
    source_state: Literal["current", "historical"]
    freshness: Literal["fresh", "stale", "unknown"]
    data_classification: DataClassification
    authority_profile: Symbol
    source_symbol: Symbol
    external_key: Name
    contributors: tuple[ResourceGeneration, ...] = Field(min_length=1, max_length=32)
    source_contributors: tuple[SourceRevisionRef, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def exact_material(self) -> Self:
        require_company(self.company_id, self.record, *self.contributors, *self.source_contributors)
        raw = self.text.encode()
        span = self.record.raw_span
        if (
            len(raw) != span.end_byte - span.start_byte
            or hashlib.sha256(raw).hexdigest() != self.record.span_sha256
        ):
            raise ValueError("Materialized bytes do not bind the raw evidence locator/hash")
        if self.record.source.source_revision_id not in {
            s.source_revision_id for s in self.source_contributors
        }:
            raise ValueError("Materialization omitted the direct source provenance")
        return self
