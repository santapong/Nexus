"""Proposed claims cannot mint verified outcomes; read ABI is not a publication permit."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import (
    BrainContract,
    Name,
    SourceTime,
    Symbol,
    ValidityInterval,
    require_company,
)
from nexus.company.brain.sources import ArtifactRevisionRef, EvidenceRef, SourceRevisionRef

CandidateKind = Literal["observation", "decision", "hypothesis", "plan", "commitment"]
ClaimKind = Literal[
    "observation", "decision", "hypothesis", "plan", "commitment", "verified_outcome"
]
ClaimText = Annotated[str, StringConstraints(min_length=1, max_length=8192)]


class ClaimCandidate(BrainContract):
    claim_id: UUID
    kind: CandidateKind
    text: ClaimText
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=32)
    source_event: SourceTime
    validity: ValidityInterval = ValidityInterval()
    origin: Literal["operator", "source", "model"]
    status: Literal["proposed"] = "proposed"

    @model_validator(mode="after")
    def proposed_provenance(self) -> Self:
        require_company(self.company_id, *self.evidence)
        if self.kind == "observation" and not self.evidence:
            raise ValueError("An observed fact candidate needs supporting source evidence")
        return self


class ClaimCandidateBatch(BrainContract):
    extraction_version: Symbol
    claims: tuple[ClaimCandidate, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def isolated(self) -> Self:
        require_company(self.company_id, *self.claims)
        if len({row.claim_id for row in self.claims}) != len(self.claims):
            raise ValueError("Claim candidates must have unique identities")
        return self


class ClaimRevisionRef(BrainContract):
    claim_id: UUID
    claim_revision_id: UUID
    revision: Name


class ClaimRecord(ClaimRevisionRef):
    """Trusted read record only; DB currently forbids verified-outcome publication."""

    resource: ResourceRef
    kind: ClaimKind
    text: ClaimText
    supporting: tuple[EvidenceRef, ...] = Field(default=(), max_length=32)
    challenging: tuple[EvidenceRef, ...] = Field(default=(), max_length=32)
    source_event: SourceTime
    ingested_at: AwareDatetime
    validity: ValidityInterval = ValidityInterval()
    origin: Literal["operator", "source", "model", "trusted_publisher"]
    status: Literal["proposed", "source_report", "superseded"]
    verification_id: UUID | None = None
    receipt_id: UUID | None = None

    @model_validator(mode="after")
    def no_false_truth(self) -> Self:
        require_company(self.company_id, self.resource, *self.supporting, *self.challenging)
        if self.kind in {"observation", "verified_outcome"} and not self.supporting:
            raise ValueError("Observed/outcome read records need supporting evidence")
        if self.origin == "model" and self.status != "proposed":
            raise ValueError("Model extraction stays proposed/unverified")
        if self.kind == "verified_outcome" and (
            self.origin != "trusted_publisher"
            or self.verification_id is None
            or self.receipt_id is None
        ):
            raise ValueError("Outcome read shape needs trusted receipt/verification references")
        return self


class ClaimLink(BrainContract):
    link_id: UUID
    subject: ClaimRevisionRef
    object: ClaimRevisionRef
    predicate: Literal["conflicts_with", "supersedes"]
    rationale: Name
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=32)
    recorded_by: UUID
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def same_claims(self) -> Self:
        require_company(self.company_id, self.subject, self.object, *self.evidence)
        if self.subject.claim_revision_id == self.object.claim_revision_id:
            raise ValueError("Claim links cannot replace/conflict with themselves")
        return self


class DerivationRecord(BrainContract):
    derivation_id: UUID
    artifact: ArtifactRevisionRef
    recipe_version: Symbol
    kind: Literal["summary", "chart", "presentation", "context", "embedding_derived_text"]
    contributors: tuple[SourceRevisionRef, ...] = Field(min_length=1, max_length=32)
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=32)
    model_recipe: Symbol | None = None
    prompt_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] | None = None
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def all_contributors(self) -> Self:
        require_company(self.company_id, self.artifact, *self.contributors, *self.evidence)
        if len({row.source_revision_id for row in self.contributors}) != len(self.contributors):
            raise ValueError("Derivation contributors must be exact and unique")
        return self
