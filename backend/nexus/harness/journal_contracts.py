"""Typed internal journal inputs and immutable public snapshots."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.contracts.base import USD, Contract, Name
from nexus.harness.lifecycle import ActionState


class LedgerScope(Contract):
    """Trusted service scope; future API integration derives it from authentication."""

    principal_id: UUID
    task_id: UUID
    trace_id: UUID


class CompanyPolicy(Contract):
    """Persisted initial company control and owner-configured cost versions."""

    owner_id: UUID
    policy_version: Name
    price_version: Name
    daily_cap_usd: Annotated[USD, Field(le=5)] = Decimal("5.00")
    work_cap_usd: USD = Decimal("1.00")

    @model_validator(mode="after")
    def valid_allocation(self) -> Self:
        """A work allowance cannot exceed the current company daily allowance."""
        if self.work_cap_usd > self.daily_cap_usd:
            raise ValueError("Work cap exceeds the daily company cap")
        return self


class ActionRecord(Contract):
    """Committed proposal and decision; authorization is distinct from execution."""

    proposal: ActionProposal
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval: ApprovalDecision | None
    state: ActionState
    consumed_at: AwareDatetime | None


class BudgetSnapshot(Contract):
    """Current ledger totals with held billing kept separate from spent money."""

    task_id: UUID
    day: date
    daily_cap_usd: USD
    daily_held_usd: USD
    daily_spent_usd: USD
    work_cap_usd: USD
    work_held_usd: USD
    work_spent_usd: USD
