"""Typed ontology edges remain distinct from scheduling dependencies and grants."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.brain.base import BrainContract, Name, ValidityInterval, require_company
from nexus.company.brain.ontology import EntityRevisionRef
from nexus.company.brain.sources import EvidenceRef

Predicate = Literal[
    "has_department",
    "owns_goal",
    "supports_goal",
    "has_support_case",
    "reports_case",
    "concerns_product",
    "cites_evidence",
    "produces_artifact",
    "verified_by",
]
ENDPOINTS: dict[str, frozenset[tuple[str, str]]] = {
    "has_department": frozenset({("Company", "Department")}),
    "owns_goal": frozenset({("Department", "Goal")}),
    "supports_goal": frozenset({("Project", "Goal"), ("Commitment", "Goal")}),
    "has_support_case": frozenset({("Product", "SupportCase")}),
    "reports_case": frozenset({("Customer", "SupportCase")}),
    "concerns_product": frozenset({("SupportCase", "Product")}),
    "cites_evidence": frozenset({("Decision", "Evidence")}),
    "produces_artifact": frozenset({("WorkItem", "Artifact")}),
    "verified_by": frozenset({("Action", "Verification")}),
}


class RelationshipCandidate(BrainContract):
    relationship_id: UUID
    predicate: Predicate
    subject: EntityRevisionRef
    object: EntityRevisionRef
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=32)
    origin: Literal["operator", "source", "model"]
    validity: ValidityInterval = ValidityInterval()
    status: Literal["proposed"] = "proposed"

    @model_validator(mode="after")
    def exact_endpoints(self) -> Self:
        require_company(self.company_id, self.subject, self.object, *self.evidence)
        if (self.subject.kind, self.object.kind) not in ENDPOINTS[self.predicate]:
            raise ValueError("Predicate does not permit these ontology endpoint kinds")
        if self.subject.entity_revision_id == self.object.entity_revision_id:
            raise ValueError("Self relationships cannot establish company knowledge")
        return self


class RelationshipRecord(BrainContract):
    relationship_id: UUID
    relationship_revision_id: UUID
    revision: Name
    predicate: Predicate
    subject: EntityRevisionRef
    object: EntityRevisionRef
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=32)
    origin: Literal["operator", "source", "model"]
    status: Literal["proposed", "source_report"]
    validity: ValidityInterval = ValidityInterval()
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def evidence_bound(self) -> Self:
        require_company(self.company_id, self.subject, self.object, *self.evidence)
        if (self.subject.kind, self.object.kind) not in ENDPOINTS[self.predicate]:
            raise ValueError("Relationship endpoint kinds are incompatible")
        if self.status == "source_report" and (not self.evidence or self.origin == "model"):
            raise ValueError("Accepted source relationships need non-model provenance")
        return self
