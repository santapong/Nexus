"""Pure exact native financial anchor before protected model output; no read permission."""

from uuid import uuid5

from nexus.company.access import CompanyControlScope
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.management.cycle_cost_contracts import NativeCostSelection
from nexus.company.management.planning_prepared_contracts import PlanningModelParameters
from nexus.harness.canonical import action_hash
from nexus.harness.journal_budget import billing_day
from nexus.harness.lifecycle import ActionState


def native_model_artifact(
    scope: CompanyControlScope,
    selected: NativeCostSelection,
    parameters: PlanningModelParameters,
) -> ArtifactRef | None:
    """Keep exact action/approval/attempt/intent/receipt/hold joins in one denial.

    Cohesion exception: this closed tuple spans >50 lines so no partial native
    record can select private output. Current owner and source checks remain
    mandatory; this descriptive artifact is never a caller-issued read permit.
    """
    action, intent, hold = selected.action.proposal, selected.intent, selected.hold
    attempt, approval, work = selected.attempt, selected.action.approval, selected.directory.work
    receipt = intent.receipt if intent else None
    if (
        intent is None
        or hold is None
        or attempt is None
        or approval is None
        or work is None
        or receipt is None
        or len(receipt.artifacts) != 1
        or selected.action.state != ActionState.AUTHORIZED
        or selected.action.consumed_at is None
        or approval.decision != "approved"
        or intent.state not in {"succeeded", "failed"}
        or intent.verification is not None
        or hold.state != "reconciled"
        or hold.actual_usd is None
        or work.counters.model_requests < 1
        or intent.intent_fence > work.fence
        or action_hash(action) != selected.action.proposal_hash
        or (action.tool, action.tool_version, action.resource)
        != (
            "model.request.v1",
            "v1",
            "model:" + parameters.registry_id,
        )
        or (action.company_id, selected.directory.company_id, work.company_id)
        != (scope.company_id,) * 3
        or (
            intent.company_id,
            intent.task_id,
            intent.trace_id,
            intent.run_id,
            intent.proposal_hash,
            intent.attempt_kind,
        )
        != (
            scope.company_id,
            action.task_id,
            action.trace_id,
            work.registration.run_id,
            selected.action.proposal_hash,
            "model_requests",
        )
        or (
            attempt.company_id,
            attempt.task_id,
            attempt.trace_id,
            attempt.attempt_id,
            attempt.kind,
            attempt.fence,
            attempt.reserved_at,
        )
        != (
            scope.company_id,
            action.task_id,
            action.trace_id,
            action.action_id,
            "model_requests",
            intent.intent_fence,
            intent.created_at,
        )
        or (approval.company_id, approval.action_id, approval.action_revision, approval.action_hash)
        != (
            scope.company_id,
            action.action_id,
            action.revision,
            selected.action.proposal_hash,
        )
        or not approval.issued_at
        <= selected.action.consumed_at
        <= intent.created_at
        < approval.expires_at
        or (hold.company_id, hold.task_id, hold.action_id, hold.amount_usd, hold.day)
        != (
            scope.company_id,
            action.task_id,
            action.action_id,
            action.estimated_cost_usd,
            billing_day(intent.created_at),
        )
        or (
            receipt.company_id,
            receipt.action_id,
            receipt.task_id,
            receipt.trace_id,
            receipt.proposal_hash,
            receipt.outcome,
            receipt.receipt_id,
        )
        != (
            scope.company_id,
            action.action_id,
            action.task_id,
            action.trace_id,
            selected.action.proposal_hash,
            intent.state,
            uuid5(action.action_id, "model-receipt-v1"),
        )
    ):
        return None
    artifact = receipt.artifacts[0]
    if scope.principal_id not in artifact.allowed_principals or (
        artifact.company_id,
        artifact.artifact_id,
        artifact.revision,
        artifact.allowed_principals,
    ) != (
        scope.company_id,
        uuid5(action.action_id, str(parameters.request_id)),
        "model-result-envelope-v1",
        (action.actor_id, approval.approver_id),
    ):
        return None
    return artifact
