"""Receipts, independent verification and ledger-derived operating reports."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.contracts.base import USD, Contract, Name
from nexus.company.contracts.knowledge import ArtifactRef


class ActionReceipt(Contract):
    """Recorded effect status, distinct from business acceptance or email delivery."""

    receipt_id: UUID
    action_id: UUID
    task_id: UUID
    trace_id: UUID
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["succeeded", "failed", "outcome_unknown"]
    recorded_at: AwareDatetime
    external_id: Name | None = None
    artifacts: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def same_company_artifacts(self) -> Self:
        """Keep receipt outputs inside the same company boundary."""
        if any(artifact.company_id != self.company_id for artifact in self.artifacts):
            raise ValueError("Receipt contains another company's artifact")
        return self


class VerificationResult(Contract):
    """Explicit acceptance verdict with criterion identities and source evidence."""

    verification_id: UUID
    action_id: UUID
    verifier_id: UUID
    verdict: Literal["pass", "reject", "inconclusive"]
    criterion_ids: tuple[Name, ...] = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = ()
    limitations: tuple[Name, ...] = ()

    @model_validator(mode="after")
    def passing_evidence(self) -> Self:
        """A model verdict cannot be passing acceptance without evidence identities."""
        if self.verdict == "pass" and not self.evidence_ids:
            raise ValueError("Passing verification needs evidence")
        return self


class OperatingReport(Contract):
    """Typed output for management reporting; factual reconciliation is a later gate."""

    report_id: UUID
    period_start: AwareDatetime
    period_end: AwareDatetime
    receipt_ids: tuple[UUID, ...] = ()
    verified_work_ids: tuple[UUID, ...] = ()
    blockers: tuple[Name, ...] = ()
    owner_decisions: tuple[Name, ...] = ()
    spent_usd: USD
    held_usd: USD

    @model_validator(mode="after")
    def valid_period(self) -> Self:
        """Reject reports with reversed or empty periods."""
        if self.period_end <= self.period_start:
            raise ValueError("Operating report period must be positive")
        return self
