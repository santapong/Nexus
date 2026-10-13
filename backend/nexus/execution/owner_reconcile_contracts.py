"""Separate owner-only control identity and trusted read-only outcome observations."""

from __future__ import annotations

from typing import Protocol, Self

from pydantic import field_validator, model_validator

from nexus.company.access import CompanyControlScope
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.base import USD, Contract
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.execution.runtime_contracts import EffectRecord, ExecutionLease


class OwnerReconciliationLease(Contract):
    """Actual owner/control identity remains separate from immutable original actor/run."""

    execution: ExecutionLease
    control_scope: CompanyControlScope

    @model_validator(mode="after")
    def same_reconciliation_company(self) -> Self:
        """A control audit operation cannot become work or executable authority."""
        if {self.company_id, self.execution.company_id, self.control_scope.company_id} != {
            self.company_id
        }:
            raise ValueError("Owner reconciliation company mismatch")
        if (
            self.execution.mode != "reconcile"
            or self.control_scope.operation_id == self.execution.task_id
        ):
            raise ValueError("Owner lease must remain a distinct reconciliation-only operation")
        return self


class ReconciliationRequest(Contract):
    """Server-validated original intent sent only to an injected read-only proof adapter."""

    lease: OwnerReconciliationLease
    proposal: ActionProposal
    effect: EffectRecord


class ReconciliationObservation(Contract):
    """Trusted adapter's observed receipt/cost and addressable source proof.

    There is no user-facing constructor/HTTP endpoint for trusted observations.
    Missing evidence is represented by the resolver returning None.
    """

    receipt: ActionReceipt
    actual_usd: USD | None
    proof: ArtifactRef

    @field_validator("actual_usd", mode="before")
    @classmethod
    def exact_observed_cost(cls, value: object) -> object:
        """Observed billing must use exact decimal data; booleans/floats are ambiguous."""
        if isinstance(value, (bool, float)):
            raise ValueError("Observed cost requires an exact decimal or unknown")
        return value

    @model_validator(mode="after")
    def source_scope(self) -> Self:
        """Source and receipt must remain inside the observed company."""
        if self.receipt.company_id != self.company_id or self.proof.company_id != self.company_id:
            raise ValueError("Reconciliation source/receipt company mismatch")
        return self


class ReadOnlyEvidenceResolver(Protocol):
    """Configured server adapter; bounded status/artifact reads, no effects or model verdicts."""

    async def resolve(self, request: ReconciliationRequest) -> ReconciliationObservation | None:
        """Return only validated observed data with protected addressable source provenance."""
        ...
