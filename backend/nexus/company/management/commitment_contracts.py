"""Immutable owner commitments are declarations, never delivery or action authority."""

from __future__ import annotations

from uuid import UUID

from pydantic import AwareDatetime, model_validator

from nexus.company.management.base import RevisionRef, Symbol, ValueContract
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.operations import CommitmentDefinition


class CommitmentRevisionRef(RevisionRef):
    commitment_id: UUID


class CommitmentRevision(CommitmentRevisionRef):
    definition: CommitmentDefinition
    recorded_by: UUID
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def exact_declaration(self) -> CommitmentRevision:
        if (self.company_id, self.commitment_id) != (
            self.definition.company_id,
            self.definition.commitment_id,
        ) or self.sha256 != canonical_sha256(self.definition):
            raise ValueError("Commitment identity/hash differs from its immutable declaration")
        return self


class CommitmentPublish(ValueContract):
    definition: CommitmentDefinition
    version: Symbol
    expected_revision_id: UUID | None


def commitment_reference(record: CommitmentRevision) -> CommitmentRevisionRef:
    return CommitmentRevisionRef(
        company_id=record.company_id,
        commitment_id=record.commitment_id,
        revision_id=record.revision_id,
        version=record.version,
        sha256=record.sha256,
    )
