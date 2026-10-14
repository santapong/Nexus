"""Sanitized owner audit shapes keep authority, execution, acceptance and billing distinct."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from nexus.company.brain.base import Flag
from nexus.company.contracts.actions import ApprovalDecision
from nexus.company.management.acceptance import ProtectedCheckProof
from nexus.company.management.base import ManagementContract, Name, Symbol, ValueContract
from nexus.company.management.cancellation_contracts import InheritedCancellation
from nexus.company.management.commitment_contracts import CommitmentRevision
from nexus.company.management.goals import Baseline, DueIntent, GoalRevisionRef, MetricDecimal
from nexus.company.management.governance import CharterRevision, MandateRevision
from nexus.company.management.lifecycle import OwnerPlanDecision, PlanRevision, PlanRevisionRef
from nexus.company.management.plans import PlanPayload, RunBinding
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.lifecycle import ActionState
from nexus.harness.limits import LoopCounters

Money = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=6, allow_inf_nan=False)]


class OwnerViewPage(ValueContract):
    after_id: UUID | None = None
    limit: Annotated[int, Field(ge=1, le=100, strict=True)] = 32


class DailyAllowance(ValueContract):
    day: date
    timezone: Literal["Asia/Bangkok"] = "Asia/Bangkok"
    cap_usd: Money
    held_usd: Money
    spent_usd: Money
    available_usd: Money


class LifetimeAllowance(ValueContract):
    """A permanent inherited slice and own task ledger; delegation is not a charge."""

    root_task_id: UUID
    parent_task_id: UUID | None
    allocated_usd: Money
    delegated_usd: Money
    own_ledger_held_usd: Money
    own_ledger_spent_usd: Money
    own_known_spent_usd: Money
    own_reserved_usd: Money
    own_actual_total_usd: Money | None
    own_billing_unconfirmed: Flag
    limits: AttemptQuota
    consumed: LoopCounters
    delegated: LoopCounters


class CompanyBudget(ValueContract):
    daily: DailyAllowance
    current_work_cap_usd: Money
    root_lifetime_allocated_usd: Money
    known_spent_usd: Money
    reserved_any_day_usd: Money
    actual_total_usd: Money | None
    billing_unconfirmed: Flag


class GoalMetricView(ValueContract):
    metric_id: Symbol
    unit: Symbol
    comparator: Literal["gt", "ge", "eq", "le", "lt"]
    target: MetricDecimal
    baseline: Baseline | None = None


class GoalView(ManagementContract):
    reference: GoalRevisionRef
    active: Flag
    title: Name
    responsible_id: UUID
    due: DueIntent
    metrics: tuple[GoalMetricView, ...] = Field(min_length=1, max_length=8)


class GovernanceHead(ValueContract):
    active: Flag


class MandateView(GovernanceHead):
    revision: MandateRevision


class CharterView(GovernanceHead):
    revision: CharterRevision


class AcceptanceAudit(ValueContract):
    acceptance_id: UUID | None
    historical_verdict: Literal["pass", "reject", "inconclusive"] | None
    recorded_at: AwareDatetime | None
    invalidated: Flag
    current_confirmed: Flag
    authorized_proofs: tuple[ProtectedCheckProof, ...] | None = None


class ReceiptAudit(ValueContract):
    action_id: UUID
    state: Literal["intent", "succeeded", "failed", "outcome_unknown"]
    receipt_id: UUID | None
    known_cost_usd: Money | None
    billing: Literal["unissued", "known", "unconfirmed"]


class WorkView(ManagementContract):
    work: RunBinding
    title: Name
    execution_state: Literal[
        "eligible", "running", "awaiting_approval", "outcome_unknown", "verifying", "blocked"
    ]
    registered_active: Flag
    lineage_active: Flag
    cancellation: InheritedCancellation | None = None
    current_plan: PlanRevisionRef | None
    independent_acceptance: AcceptanceAudit
    lifetime: LifetimeAllowance
    live_lease_until: AwareDatetime | None
    receipts: tuple[ReceiptAudit, ...] = Field(default=(), max_length=100)
    receipts_next_after_id: UUID | None = None


class ApprovalView(ManagementContract):
    """Exact native decision metadata; private action inputs/receipt text are not exposed."""

    action_id: UUID
    task_id: UUID
    actor_id: UUID
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool: Name
    tool_version: Name
    resource_symbol: Name
    estimated_cost_usd: Money
    state: ActionState
    owner_decision: ApprovalDecision | None
    standing_grant_id: UUID | None
    authority_observation: Literal["pending", "exact_recorded", "standing_recorded", "unavailable"]
    consumed_at: AwareDatetime | None


class ApprovalPage(ManagementContract):
    observed_at: AwareDatetime
    approvals: tuple[ApprovalView, ...] = Field(default=(), max_length=100)
    pending_plans: tuple[PlanRevision, ...] = Field(default=(), max_length=100)
    next_after_id: UUID | None = None
    next_plan_after_id: UUID | None = None


class PlanView(ManagementContract):
    reference: PlanRevisionRef
    state: Literal["proposed", "approved", "revoked"]
    is_current_head: Flag
    declaration: PlanPayload
    decision: OwnerPlanDecision | None
    work: tuple[WorkView, ...] = Field(default=(), max_length=100)
    observed_at: AwareDatetime


class CommitmentView(ValueContract):
    revision: CommitmentRevision
    binding_state: Literal["current", "stale", "inactive"]


class PlanHeadView(ValueContract):
    reference: PlanRevisionRef
    goal: GoalRevisionRef
    state: Literal["proposed", "approved", "revoked"]
    decision: OwnerPlanDecision | None


class CompanyView(ManagementContract):
    observed_at: AwareDatetime
    owner_id: UUID
    paused: Flag
    budget: CompanyBudget
    mandate: MandateView | None
    charters: tuple[CharterView, ...] = Field(default=(), max_length=100)
    goals: tuple[GoalView, ...] = Field(default=(), max_length=100)
    plans: tuple[PlanHeadView, ...] = Field(default=(), max_length=100)
    commitments: tuple[CommitmentView, ...] = Field(default=(), max_length=100)
    next_charter_after_id: UUID | None = None
    next_goal_after_id: UUID | None = None
    next_plan_after_id: UUID | None = None
    next_commitment_after_id: UUID | None = None


class TodayView(ManagementContract):
    observed_at: AwareDatetime
    paused: Flag
    budget: CompanyBudget
    due: tuple[CommitmentView, ...] = Field(default=(), max_length=100)
    decisions: ApprovalPage
    next_due_after_id: UUID | None = None
