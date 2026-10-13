"""Closed company ontology fields; knowledge objects cannot carry execution authority."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import (
    BrainContract,
    Name,
    SourceTime,
    Symbol,
    ValidityInterval,
    ValueContract,
    require_company,
)
from nexus.company.brain.sources import EvidenceRef

EntityKind = Literal[
    "Company",
    "Department",
    "Principal",
    "Product",
    "Project",
    "Goal",
    "WorkItem",
    "Customer",
    "SupportCase",
    "Decision",
    "Commitment",
    "Evidence",
    "Artifact",
    "Action",
    "Verification",
    "Budget",
    "AuthorityPolicy",
]


class CompanyContent(ValueContract):
    kind: Literal["Company"] = "Company"
    label: Name


class DepartmentContent(ValueContract):
    kind: Literal["Department"] = "Department"
    label: Name
    charter_version: Symbol | None = None


class PrincipalContent(ValueContract):
    kind: Literal["Principal"] = "Principal"
    label: Name
    principal_id: UUID


class ProductContent(ValueContract):
    kind: Literal["Product"] = "Product"
    label: Name
    product_symbol: Symbol | None = None


class ProjectContent(ValueContract):
    kind: Literal["Project"] = "Project"
    label: Name


class GoalContent(ValueContract):
    kind: Literal["Goal"] = "Goal"
    label: Name
    metric: Name | None = None
    due: SourceTime | None = None


class WorkItemContent(ValueContract):
    kind: Literal["WorkItem"] = "WorkItem"
    label: Name
    task_id: UUID


class CustomerContent(ValueContract):
    kind: Literal["Customer"] = "Customer"
    label: Name
    external_identity: Name | None = None


class SupportCaseContent(ValueContract):
    kind: Literal["SupportCase"] = "SupportCase"
    label: Name
    external_identity: Name | None = None


class DecisionContent(ValueContract):
    kind: Literal["Decision"] = "Decision"
    label: Name
    rationale: Name | None = None


class CommitmentContent(ValueContract):
    kind: Literal["Commitment"] = "Commitment"
    label: Name
    due: SourceTime
    recipient_reference: Name | None = None


class EvidenceContent(ValueContract):
    kind: Literal["Evidence"] = "Evidence"
    label: Name
    evidence_id: UUID


class ArtifactContent(ValueContract):
    kind: Literal["Artifact"] = "Artifact"
    label: Name
    artifact_revision_id: UUID


class ActionContent(ValueContract):
    kind: Literal["Action"] = "Action"
    label: Name
    action_id: UUID


class VerificationContent(ValueContract):
    kind: Literal["Verification"] = "Verification"
    label: Name
    verification_id: UUID


class BudgetContent(ValueContract):
    kind: Literal["Budget"] = "Budget"
    label: Name
    budget_reference: Symbol


class AuthorityPolicyContent(ValueContract):
    kind: Literal["AuthorityPolicy"] = "AuthorityPolicy"
    label: Name
    policy_version: Symbol


EntityContent = Annotated[
    CompanyContent
    | DepartmentContent
    | PrincipalContent
    | ProductContent
    | ProjectContent
    | GoalContent
    | WorkItemContent
    | CustomerContent
    | SupportCaseContent
    | DecisionContent
    | CommitmentContent
    | EvidenceContent
    | ArtifactContent
    | ActionContent
    | VerificationContent
    | BudgetContent
    | AuthorityPolicyContent,
    Field(discriminator="kind"),
]


class EntityRevisionRef(BrainContract):
    entity_id: UUID
    entity_revision_id: UUID
    revision: Name
    kind: EntityKind


class EntityRevisionRecord(EntityRevisionRef):
    resource: ResourceRef
    content: EntityContent
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=32)
    source_event: SourceTime
    ingested_at: AwareDatetime
    validity: ValidityInterval = ValidityInterval()
    origin: Literal["operator", "source", "model"]
    status: Literal["proposed", "source_report"]

    @model_validator(mode="after")
    def bounded_entity(self) -> Self:
        require_company(self.company_id, self.resource, *self.evidence)
        if self.kind != self.content.kind:
            raise ValueError("Entity fields do not match its declared kind")
        if self.origin == "model" and self.status != "proposed":
            raise ValueError("Model output is a proposal, not accepted company state")
        return self
