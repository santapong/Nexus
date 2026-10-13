"""Typed commitments, actual report projections and deterministic eligibility declarations."""

from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.brain.base import Flag
from nexus.company.management.base import (
    SHA256,
    ManagementContract,
    Name,
    ValueContract,
    require_company,
)
from nexus.company.management.goals import DueIntent, GoalRevisionRef
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.plans import RunBinding

LedgerUSD = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=6, allow_inf_nan=False)]


class CommitmentDefinition(ManagementContract):
    commitment_id: UUID
    goal: GoalRevisionRef
    plan: PlanRevisionRef
    responsible_id: UUID
    deliverable: Name
    due: DueIntent
    work: tuple[RunBinding, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def declaration_only(self) -> Self:
        require_company(self.company_id, self.goal, self.plan, *self.work)
        if len({row.task_id for row in self.work}) != len(self.work):
            raise ValueError("Commitment work identities must be unique")
        return self


class WorkProjection(ManagementContract):
    work: RunBinding
    execution_state: Literal[
        "eligible", "running", "awaiting_approval", "outcome_unknown", "verifying", "blocked"
    ]
    registered_active: Flag
    acceptance: Literal["pending", "accepted", "rejected", "inconclusive", "invalidated"]
    acceptance_id: UUID | None = None
    billing: Literal["known", "unconfirmed"]

    @model_validator(mode="after")
    def truthful_shape(self) -> Self:
        require_company(self.company_id, self.work)
        if (self.acceptance == "pending") != (self.acceptance_id is None):
            raise ValueError(
                "Accepted/rejected/inconclusive history requires its actual acceptance identity"
            )
        return self


EligibilityState = Literal["eligible", "waiting", "blocked", "cancelled"]
EligibilityReason = Literal[
    "ready",
    "dependency_unaccepted",
    "verification_result_available",
    "approval_pending",
    "budget_exhausted",
    "company_paused",
    "mandate_revoked",
    "scope_unavailable",
    "outcome_unknown",
    "billing_unknown",
    "work_cancelled",
    "versions_stale",
    "source_unavailable",
    "verification_unbound",
    "due_pending",
    "dispatch_active",
    "acceptance_invalidated",
    "already_accepted",
]


class Eligibility(ManagementContract):
    work: RunBinding
    plan: PlanRevisionRef
    state: EligibilityState
    reason: EligibilityReason

    @model_validator(mode="after")
    def bounded_reason(self) -> Self:
        require_company(self.company_id, self.work, self.plan)
        if self.state == "eligible" and self.reason not in {
            "ready",
            "verification_result_available",
        }:
            raise ValueError("A blocked/waiting reason cannot authorize eligibility")
        return self


class LedgerSnapshot(ValueContract):
    held_usd: LedgerUSD
    spent_usd: LedgerUSD
    source_sha256: SHA256
    observed_at: AwareDatetime


class ReportSnapshot(ManagementContract):
    report_id: UUID
    period_start: AwareDatetime
    period_end: AwareDatetime
    ledger: LedgerSnapshot
    work: tuple[WorkProjection, ...] = Field(default=(), max_length=100)
    blockers: tuple[Name, ...] = Field(default=(), max_length=100)
    owner_decision_ids: tuple[UUID, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def actual_projection(self) -> Self:
        require_company(self.company_id, *self.work)
        if self.period_end <= self.period_start:
            raise ValueError("Report period must be ordered")
        if len({row.work.task_id for row in self.work}) != len(self.work):
            raise ValueError("A report cannot duplicate logical work")
        return self
