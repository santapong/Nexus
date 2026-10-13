"""Sealed evaluator-only management reports; never import from application code or seed ledgers."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from nexus.company.brain.base import Flag, Ordinal, ValueContract


class ActionState(ValueContract):
    action_id: UUID
    current_revision: str
    expected_revision: str
    issued: Literal[False]
    resource: str
    state: Literal["planned"]


class DeploymentState(ValueContract):
    current_production_state: Literal["unverified"]
    deployment_receipt: None


class AuthorityBudget(ValueContract):
    authority_changes_allowed_from_source_text: Literal[False]
    daily_cap_usd: Decimal
    held_usd: Decimal
    mandate_version: str
    oversight: Literal["supervised"]
    policy_version: str
    spent_usd: Decimal
    tools_granted: tuple[str, ...]
    work_cap_usd: Decimal


class VerificationState(ValueContract):
    verdict: Literal["reject", "inconclusive"]
    work_completed: Literal[False]
    artifact_id: UUID | None = None
    criterion_ids: tuple[str, ...] = ()
    verification_id: UUID | None = None
    verifier_id: UUID | None = None
    artifact_present: Flag | None = None
    behavior_checked: Flag | None = None
    error_type: str | None = None
    error_marker: str | None = None
    passing_evidence_ids: tuple[UUID, ...] = ()


class NotificationState(ValueContract):
    delivery_receipt: None
    delivery_status: Literal["unknown"]
    provider_reference: str
    request_status: Literal["accepted"]
    work_completed: Literal[False]


class EffectState(ValueContract):
    action_id: UUID
    actual_calls_executed_by_fixture: Literal[0]
    effect_id: UUID
    issued_in_sealed_fixture_history: Literal[True]
    may_automatically_repeat: Literal[False]
    outcome: Literal["outcome_unknown"]
    receipt: None
    reconciliation: None
    recorded_issue_count: Literal[1]


class WorkState(ValueContract):
    blocking_dependency: Literal["owner_input"]
    owner_id: UUID
    state: Literal["blocked"]
    task_id: UUID
    work_alias: str
    work_completed: Literal[False]


class CompletedProjection(ValueContract):
    completion_basis: Literal["sealed_synthetic_projection_not_live_proof"]
    state: Literal["completed"]
    task_id: UUID


class EligibilityProjection(ValueContract):
    active_scope: Flag
    depends_on: tuple[str, ...] = ()
    other_prerequisites_satisfied: Flag
    remaining_usd: Decimal
    required_approval_satisfied: Flag
    state: Literal["ready", "awaiting_approval"]
    task_id: UUID


class WorkEligibility(ValueContract):
    W1: CompletedProjection
    W2: EligibilityProjection
    W3: EligibilityProjection


class LifetimeBudget(ValueContract):
    allocation_usd: Decimal
    child_registered: Literal[False]
    delegated_usd: Decimal
    held_usd: Decimal
    parent_task_id: UUID
    proposed_child_task_id: UUID
    proposed_resume_segment_id: UUID
    remaining_usd: Decimal
    resume_authorized: Literal[False]
    root_task_id: UUID
    spent_usd: Decimal


class OversightPolicy(ValueContract):
    automatic_promotion_allowed: Literal[False]
    count_basis: Literal["sealed_synthetic_projection_not_live_proof"]
    oversight: Literal["supervised"]
    owner_approved_policy_change: Literal[False]
    owner_id: UUID
    policy_version: str
    reviewed_completed_count: Ordinal


class SealedProjection(ValueContract):
    """Outer fixture provenance makes the test-only meaning explicit in every report."""

    alias: str
    as_of: AwareDatetime
    authority: Literal["sealed_test_setup_only_not_live_execution_or_model_output"]
    case_id: str
    company_id: UUID
    projection_id: UUID


class ActionProjection(SealedProjection):
    kind: Literal["action_precondition"]
    fields: ActionState


class DeploymentProjection(SealedProjection):
    kind: Literal["deployment_evidence"]
    fields: DeploymentState


class BudgetProjection(SealedProjection):
    kind: Literal["authority_budget"]
    fields: AuthorityBudget


class VerificationProjection(SealedProjection):
    kind: Literal["verification_state"]
    fields: VerificationState


class NotificationProjection(SealedProjection):
    kind: Literal["notification_state"]
    fields: NotificationState


class EffectProjection(SealedProjection):
    kind: Literal["effect_state"]
    fields: EffectState


class WorkProjection(SealedProjection):
    kind: Literal["work_state"]
    fields: WorkState


class EligibilityStateProjection(SealedProjection):
    kind: Literal["work_eligibility"]
    fields: WorkEligibility


class LifetimeProjection(SealedProjection):
    kind: Literal["registered_lifetime_budget"]
    fields: LifetimeBudget


class PolicyProjection(SealedProjection):
    kind: Literal["oversight_policy"]
    fields: OversightPolicy


Projection = Annotated[
    ActionProjection
    | DeploymentProjection
    | BudgetProjection
    | VerificationProjection
    | NotificationProjection
    | EffectProjection
    | WorkProjection
    | EligibilityStateProjection
    | LifetimeProjection
    | PolicyProjection,
    Field(discriminator="kind"),
]
