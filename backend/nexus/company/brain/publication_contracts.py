"""Internal knowledge commands exclude truth promotion, roles, prices and execution state."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import (
    BrainContract,
    Name,
    SourceTime,
    Symbol,
    ValidityInterval,
    require_company,
)
from nexus.company.brain.claims import CandidateKind, ClaimRevisionRef, ClaimText
from nexus.company.brain.ontology import EntityContent, EntityRevisionRef
from nexus.company.brain.relationships import ENDPOINTS, Predicate
from nexus.company.brain.sources import EvidenceRef


def _unique_evidence(values: tuple[EvidenceRef, ...]) -> None:
    if len(set(values)) != len(values):
        raise ValueError("Publication evidence references must be unique")


class ClaimDraft(BrainContract):
    claim_id: UUID
    kind: CandidateKind
    text: ClaimText
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=32)
    source_event: SourceTime
    validity: ValidityInterval = ValidityInterval()

    @model_validator(mode="after")
    def supported(self) -> Self:
        require_company(self.company_id, *self.evidence)
        _unique_evidence(self.evidence)
        if len(self.text.encode()) > 8192:
            raise ValueError("Claim text exceeds its UTF8 byte bound")
        if self.kind == "observation" and not self.evidence:
            raise ValueError("An observation requires exact supporting source evidence")
        return self


class ClaimPublication(BrainContract):
    resource: ResourceRef
    draft: ClaimDraft
    revision: Name
    challenging: tuple[EvidenceRef, ...] = Field(default=(), max_length=32)
    expected_previous_revision_id: UUID | None = None

    @model_validator(mode="after")
    def same_company(self) -> Self:
        require_company(self.company_id, self.resource, self.draft, *self.challenging)
        _unique_evidence(self.challenging)
        if set(self.draft.evidence) & set(self.challenging):
            raise ValueError("Evidence cannot both support and challenge the same revision")
        return self


class ClaimPublicationBatch(BrainContract):
    extraction_version: Symbol
    claims: tuple[ClaimPublication, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        require_company(self.company_id, *self.claims)
        if len({row.draft.claim_id for row in self.claims}) != len(self.claims):
            raise ValueError("A proposal batch must contain distinct logical claims")
        return self


class ClaimLinkPublication(BrainContract):
    link_id: UUID
    subject: ClaimRevisionRef
    object: ClaimRevisionRef
    predicate: Literal["conflicts_with", "supersedes"]
    rationale: Name
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def exact_claims(self) -> Self:
        require_company(self.company_id, self.subject, self.object, *self.evidence)
        _unique_evidence(self.evidence)
        if self.subject.claim_revision_id == self.object.claim_revision_id:
            raise ValueError("A claim cannot conflict with or supersede itself")
        return self


class EntityPublication(BrainContract):
    entity_id: UUID
    resource: ResourceRef
    content: EntityContent
    revision: Name
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=32)
    source_event: SourceTime
    validity: ValidityInterval = ValidityInterval()
    expected_previous_revision_id: UUID | None = None

    @model_validator(mode="after")
    def isolated(self) -> Self:
        require_company(self.company_id, self.resource, *self.evidence)
        _unique_evidence(self.evidence)
        if len(self.content.model_dump_json().encode()) > 32768:
            raise ValueError("Entity content exceeds its UTF8 byte bound")
        return self


class RelationshipPublication(BrainContract):
    relationship_id: UUID
    revision: Name
    predicate: Predicate
    subject: EntityRevisionRef
    object: EntityRevisionRef
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=32)
    validity: ValidityInterval = ValidityInterval()

    @model_validator(mode="after")
    def exact_endpoints(self) -> Self:
        require_company(self.company_id, self.subject, self.object, *self.evidence)
        _unique_evidence(self.evidence)
        if (self.subject.kind, self.object.kind) not in ENDPOINTS[
            self.predicate
        ] or self.subject.entity_revision_id == self.object.entity_revision_id:
            raise ValueError("Relationship endpoints are incompatible")
        return self
