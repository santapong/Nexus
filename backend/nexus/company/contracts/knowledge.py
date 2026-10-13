"""Provenance and permission-bearing evidence/context contracts."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, PositiveInt, model_validator

from nexus.company.contracts.base import Contract, Name


class ArtifactRef(Contract):
    """Addressable immutable content; actual access remains a runtime check."""

    artifact_id: UUID
    reference: Name
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: Name
    allowed_principals: tuple[UUID, ...] = ()


class Evidence(Contract):
    """A sourced observation with distinct source-event and ingestion times."""

    evidence_id: UUID
    source: ArtifactRef
    event_at: AwareDatetime
    ingested_at: AwareDatetime
    summary: Name

    @model_validator(mode="after")
    def source_company(self) -> Self:
        """Prevent a nested source from crossing a company boundary."""
        if self.source.company_id != self.company_id:
            raise ValueError("Evidence source belongs to another company")
        return self


class Claim(Contract):
    """Typed claim; a hypothesis or plan is never a verified outcome."""

    claim_id: UUID
    kind: Literal["observation", "decision", "hypothesis", "plan", "commitment", "verified_outcome"]
    text: Name
    evidence_ids: tuple[UUID, ...] = ()
    allowed_principals: tuple[UUID, ...] = ()
    verification_id: UUID | None = None
    supersedes: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def support_required(self) -> Self:
        """Require provenance for observed facts and verification identity for outcomes."""
        if self.kind in {"observation", "verified_outcome"} and not self.evidence_ids:
            raise ValueError("Observed facts need source evidence")
        if self.kind == "verified_outcome" and self.verification_id is None:
            raise ValueError("Verified outcomes need a verification record")
        return self


class ContextBundle(Contract):
    """One context manifest shared by all roles, with bounded artifact references."""

    task_id: UUID
    trace_id: UUID
    principal_id: UUID
    mandate_version: Name
    policy_version: Name
    budget_version: Name
    acceptance: tuple[Name, ...] = Field(min_length=1)
    claims: tuple[Claim, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    attachments: tuple[ArtifactRef, ...] = ()
    workspace_files: tuple[ArtifactRef, ...] = ()
    omitted_references: tuple[Name, ...] = ()
    token_limit: PositiveInt

    @model_validator(mode="after")
    def accessible_sources(self) -> Self:
        """Reject cross-company records, inaccessible sources and unresolved citations."""
        artifacts = (*self.attachments, *self.workspace_files, *(e.source for e in self.evidence))
        records = (*self.claims, *self.evidence, *artifacts)
        if any(record.company_id != self.company_id for record in records):
            raise ValueError("Context contains another company's record")
        if any(self.principal_id not in artifact.allowed_principals for artifact in artifacts):
            raise ValueError("Context source is not accessible to this principal")
        if any(self.principal_id not in claim.allowed_principals for claim in self.claims):
            raise ValueError("Context claim is not accessible to this principal")
        evidence_ids = {entry.evidence_id for entry in self.evidence}
        if any(not set(claim.evidence_ids) <= evidence_ids for claim in self.claims):
            raise ValueError("Context claim has an unresolved evidence reference")
        return self
