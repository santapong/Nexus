"""Neutral descriptive plan choice; no current proof, owner decision or execution authority."""

from typing import Self
from uuid import UUID

from pydantic import model_validator

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.base import SHA256, ManagementContract, Symbol, require_company


class StrategySelectionRef(ManagementContract):
    """Descriptive comparison ref only; an actual owner decision must bind it later."""

    brief: ArtifactRevisionRef
    acceptance_id: UUID
    candidate_id: Symbol
    candidate_scope_sha256: SHA256

    @model_validator(mode="after")
    def same_company(self) -> Self:
        require_company(self.company_id, self.brief)
        return self
