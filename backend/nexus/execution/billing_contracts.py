"""Internal observed-invoice billing continuation, distinct from receipt/business acceptance."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_serializer, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.base import USD, Contract, Name
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.execution.owner_reconcile_contracts import OwnerReconciliationLease
from nexus.execution.runtime_contracts import ExecutionLease


def receipt_digest(value: str) -> str:
    """Hash exact persisted bytes, with no JSON parse/reserialization before comparison."""
    return hashlib.sha256(value.encode()).hexdigest()


class OwnerBillingLease(Contract):
    """Recording-only owner fence and immutable target known receipt; no actor authority."""

    execution: ExecutionLease
    control_scope: CompanyControlScope
    action_id: UUID
    receipt_id: UUID
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    def owner_lease(self) -> OwnerReconciliationLease:
        """Adapt to the shared ownership guard only inside trusted server composition."""
        return OwnerReconciliationLease(
            company_id=self.company_id, execution=self.execution, control_scope=self.control_scope
        )

    @model_validator(mode="after")
    def owner_binding(self) -> Self:
        self.owner_lease()
        return self


class BillingLookupRequest(Contract):
    """Canonical original action/known receipt sent to configured read-only source verification."""

    lease: OwnerBillingLease
    proposal: ActionProposal
    receipt: ActionReceipt
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class BillingObservation(Contract):
    """Validated actual invoice event; known outcome/missing usage cannot establish a charge."""

    evidence_id: UUID
    action_id: UUID
    task_id: UUID
    trace_id: UUID
    run_id: UUID
    receipt_id: UUID
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    external_id: Name | None
    price_version: Name
    currency: Literal["USD"]
    provider: Name
    source_observation_id: Name
    provider_reference: Name | None
    invoice_reference: Name
    actual_usd: USD
    proof: ArtifactRef
    observed_at: AwareDatetime
    source_checked_at: AwareDatetime

    @field_validator("actual_usd", mode="before")
    @classmethod
    def exact_amount(cls, value: object) -> object:
        if isinstance(value, (bool, float)):
            raise ValueError("Billing observation requires an exact observed Decimal amount")
        return value

    @field_serializer("actual_usd")
    def stable_amount(self, value: Decimal) -> str:
        return format(value.quantize(Decimal("0.000001")), "f")

    @model_validator(mode="after")
    def source_binding(self) -> Self:
        if self.proof.company_id != self.company_id or self.source_checked_at < self.observed_at:
            raise ValueError("Billing source company/date binding is invalid")
        if self.external_id != self.provider_reference:
            raise ValueError("Invoice provider reference must match its exact issued external ID")
        return self


def observation_digest(value: BillingObservation) -> str:
    """Repeated reads may have a later check time; all original charge/proof fields must match."""
    payload = json.dumps(
        value.model_dump(mode="json", exclude={"source_checked_at"}),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class BillingEvidenceRecord(Contract):
    """Persisted immutable observed bill, with the actual owner operation and first check date."""

    observation: BillingObservation
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    owner_id: UUID
    operation_id: UUID
    operation_trace_id: UUID
    lease_fence: int = Field(gt=0, strict=True)
    recorded_at: AwareDatetime

    @property
    def actual_usd(self) -> Decimal:
        """Expose the observed amount without inventing a second independently mutable value."""
        return self.observation.actual_usd


class ReadOnlyBillingResolver(Protocol):
    """Trusted read-only source adapter, never a user-accepted amount/verdict/callable."""

    async def resolve(self, request: BillingLookupRequest) -> BillingObservation | None:
        """Read bounded bytes and verify mapping/hash/current source ACL; None means unknown."""
        ...

    async def validate_before_commit(
        self,
        session: AsyncSession,
        request: BillingLookupRequest,
        observation: BillingObservation,
        now: datetime,
    ) -> None:
        """Fast database/protected-index checks under the mutex, without file/provider I/O."""
        ...
