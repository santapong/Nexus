"""Bounded actual-artifact read DTO; no caller paths or selected-evidence substitution."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.base import SHA256, BrainContract, Flag, require_company
from nexus.company.brain.sources import ArtifactRevisionRef, SourceHead, SourceRevisionRef, UTF8Span
from nexus.core.llm.company_registry import DataClassification


class ArtifactSlice(BrainContract):
    artifact: ArtifactRevisionRef
    span: UTF8Span
    span_sha256: SHA256
    text: Annotated[str, StringConstraints(min_length=1, max_length=16384)]
    source_contributors: tuple[SourceRevisionRef, ...] = Field(min_length=1, max_length=32)
    contributors: tuple[ResourceGeneration, ...] = Field(min_length=1, max_length=32)
    source_heads: tuple[SourceHead, ...] = Field(min_length=1, max_length=32)
    data_classification: DataClassification
    source_state: Literal["current", "historical"]
    has_more: Flag

    @model_validator(mode="after")
    def exact_bytes(self) -> Self:
        require_company(
            self.company_id,
            self.artifact,
            *self.source_contributors,
            *self.contributors,
            *self.source_heads,
        )
        raw = self.text.encode()
        if (
            len(raw) != self.span.end_byte - self.span.start_byte
            or hashlib.sha256(raw).hexdigest() != self.span_sha256
            or self.span.end_byte > self.artifact.byte_length
        ):
            raise ValueError("Artifact slice bytes/hash/locator disagree")
        if self.has_more != (self.span.end_byte < self.artifact.byte_length):
            raise ValueError("Artifact continuation disagrees with actual full byte length")
        return self
