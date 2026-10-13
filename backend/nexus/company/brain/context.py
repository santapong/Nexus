"""Shared context byte limits and provenance; no invented aggregate token allowance."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.base import (
    BrainContract,
    Count,
    Name,
    Ordinal,
    Symbol,
    ValueContract,
    require_company,
)
from nexus.company.brain.retrieval import CitationHandle, SearchRequest
from nexus.company.brain.sources import EvidenceRef, SourceHead
from nexus.core.llm.company_registry import DataClassification


class ContextLimits(ValueContract):
    """Required trusted runtime policy, not an externally accepted request budget."""

    policy_version: Symbol
    max_materialized_bytes: Annotated[Count, Field(le=65536)] = 65536
    max_span_bytes: Annotated[Count, Field(le=16384)] = 16384
    max_sources: Annotated[Count, Field(le=32)] = 32
    max_sections: Annotated[Count, Field(le=20)] = 20
    max_inclusions: Annotated[Count, Field(le=20)] = 20
    max_prompt_bytes: Annotated[Count, Field(le=100000)] = 100000


class SectionSelection(BrainContract):
    artifact_revision_id: UUID
    sections: tuple[Name, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_sections(self) -> Self:
        if len(set(self.sections)) != len(self.sections):
            raise ValueError("Explicit sections must be unique")
        return self


class ContextSelection(BrainContract):
    search: SearchRequest | None = None
    explicit_evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=32)
    explicit_sections: tuple[SectionSelection, ...] = Field(default=(), max_length=20)
    attachments: tuple[EvidenceRef, ...] = Field(default=(), max_length=20)
    workspace_files: tuple[EvidenceRef, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def bounded_selection(self) -> Self:
        require_company(
            self.company_id,
            self.search,
            *self.explicit_sections,
            *self.attachments,
            *self.workspace_files,
        )
        return self


class ContextAuthorityState(BrainContract):
    """Output of a trusted current-state provider; source/model text cannot supply it."""

    mandate_version: Symbol
    policy_version: Symbol
    budget_version: Symbol
    charter_version: Symbol | None = None
    role_system_text: Annotated[str, StringConstraints(min_length=1, max_length=16384)]
    acceptance: tuple[Name, ...] = Field(default=(), max_length=100)
    goal_ancestry: tuple[UUID, ...] = Field(default=(), max_length=16)
    feedback: tuple[EvidenceRef, ...] = Field(default=(), max_length=20)
    data_classification: DataClassification
    model_profile: Symbol | None = None
    model_recipe: Symbol | None = None
    model_recipe_revision: Symbol | None = None

    @model_validator(mode="after")
    def feedback_scope(self) -> Self:
        require_company(self.company_id, *self.feedback)
        if (self.model_recipe is None) != (self.model_recipe_revision is None):
            raise ValueError("A model recipe must include its exact revision")
        return self


class ContextInclusion(BrainContract):
    handle: CitationHandle
    data_classification: DataClassification
    purpose: Literal["evidence", "attachment", "workspace", "feedback"]
    disposition: Literal["included", "excerpted", "summarized", "stale"]
    included_bytes: Count

    @model_validator(mode="after")
    def same_handle(self) -> Self:
        require_company(self.company_id, self.handle)
        return self


class ContextOmission(BrainContract):
    """Only already-authorized references can be listed; no hidden source details."""

    evidence: EvidenceRef
    reason: Literal["byte_limit", "span_limit", "source_limit", "section_selection", "stale"]
    section: Name | None = None

    @model_validator(mode="after")
    def same_evidence(self) -> Self:
        require_company(self.company_id, self.evidence)
        return self


class ContextManifest(BrainContract):
    context_id: UUID
    principal_id: UUID
    operation_id: UUID
    trace_id: UUID
    task_id: UUID | None = None
    task_trace_id: UUID | None = None
    actor_id: UUID | None = None
    authority: ContextAuthorityState
    policy_version: Symbol
    retrieval_recipe: Symbol
    render_recipe: Symbol
    inclusions: tuple[ContextInclusion, ...] = Field(default=(), max_length=20)
    omissions: tuple[ContextOmission, ...] = Field(default=(), max_length=256)
    contributors: tuple[ResourceGeneration, ...] = Field(default=(), max_length=32)
    source_heads: tuple[SourceHead, ...] = Field(default=(), max_length=32)
    data_classification: DataClassification
    token_qualification: Literal["unavailable", "qualified"] = "unavailable"
    qualified_input_tokens: Count | None = None
    materialized_bytes: Annotated[Ordinal, Field(le=65536)]
    prompt_bytes: Annotated[Count, Field(le=100000)]
    prompt_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def scope_and_qualification(self) -> Self:
        require_company(
            self.company_id,
            self.authority,
            *self.inclusions,
            *self.omissions,
            *self.contributors,
            *self.source_heads,
        )
        if (self.token_qualification == "qualified") != (self.qualified_input_tokens is not None):
            raise ValueError("Read-only context cannot invent token qualification")
        if self.token_qualification == "qualified" and not all(
            (
                self.authority.model_profile,
                self.authority.model_recipe,
                self.authority.model_recipe_revision,
            )
        ):
            raise ValueError("Qualified model context needs explicit profile/recipe binding")
        permitted = {
            "public": {"public"},
            "internal": {"public", "internal"},
            "confidential": {"public", "internal", "confidential"},
            "restricted": {"public", "internal", "confidential", "restricted"},
        }[self.data_classification]
        if self.authority.data_classification not in permitted or any(
            row.data_classification not in permitted for row in self.inclusions
        ):
            raise ValueError("Context classification cannot downgrade trusted runtime content")
        return self


class AssembledContext(BrainContract):
    manifest: ContextManifest
    system_text: Annotated[str, StringConstraints(min_length=1, max_length=100000)]
    input_text: Annotated[str, StringConstraints(min_length=1, max_length=100000)]

    @model_validator(mode="after")
    def exact_prompt(self) -> Self:
        require_company(self.company_id, self.manifest)
        raw = (self.system_text + "\n" + self.input_text).encode()
        if (
            len(raw) != self.manifest.prompt_bytes
            or hashlib.sha256(raw).hexdigest() != self.manifest.prompt_sha256
        ):
            raise ValueError("Actual rendered prompt and manifest hash/bytes disagree")
        return self
