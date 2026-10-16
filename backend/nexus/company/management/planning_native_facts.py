"""Current owner READ of exact native/protected planning provenance, never a lease."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.native_fact_inputs import source_artifact_reference
from nexus.company.brain.source_models import BrainSourceHead, BrainSourceRevision
from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.control_support import db_clock
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.governance_models import ManagementGoalHead
from nexus.company.management.owner_view_sources import (
    OwnerViewSources,
    owner_brain_scope,
    source_disclosure,
)
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanHead,
    ManagementPlanRevision,
    ManagementPlanTask,
)
from nexus.company.management.plan_registration import registration, require_native_task
from nexus.company.management.revision_store import plan_record
from nexus.company.management.transactions import (
    ManagementDeniedError,
)
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import snapshot
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, CostHold, JournalAction
from nexus.harness.lifecycle import ActionState

if TYPE_CHECKING:
    from nexus.company.management.planning_proposal_bridge import PlanningProposalTemplate


def clock_us() -> int:
    return time.monotonic_ns() // 1000


def read_end(end_us: int | None = None) -> int:
    if end_us is not None and (type(end_us) is not int or end_us <= 0):
        raise ValueError("Planning read needs a finite original deadline")
    result = min(clock_us() + 30_000_000, end_us) if end_us is not None else clock_us() + 30_000_000
    require_time(result)
    return result


def require_time(end_us: int) -> None:
    if clock_us() >= end_us:
        raise TimeoutError("Planning provenance read expired")


@dataclass(frozen=True)
class NativePlanning:
    proposal: ActionProposal
    receipt: ActionReceipt
    intent_created_at: datetime
    actual_usd: Decimal


async def require_base_plan(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    target_id: UUID | None,
    template: PlanningProposalTemplate,
) -> None:
    base = template.base_plan
    row = await session.get(ManagementPlanRevision, (scope.company_id, base.plan_revision_id))
    head = await session.get(ManagementPlanHead, (scope.company_id, base.plan_id))
    goal_head = await session.get(ManagementGoalHead, (scope.company_id, base.payload.goal.goal_id))
    if (
        row is None
        or plan_record(row) != base
        or head is None
        or head.state != "approved"
        or goal_head is None
        or not goal_head.active
    ):
        raise ManagementDeniedError("Exact stored bootstrap/current goal is unavailable")
    await GoalStore._current(session, scope, base.payload.goal)
    if head.current_revision_id != base.plan_revision_id:
        target = (
            await session.get(ManagementPlanRevision, (scope.company_id, target_id))
            if target_id
            else None
        )
        if target is None or head.current_revision_id != target_id:
            raise ManagementDeniedError("Planning head CAS changed")
        parsed = plan_record(target)
        if (
            parsed.plan_id != base.plan_id
            or parsed.revision != base.revision + 1
            or parsed.payload.planning_origin is None
        ):
            raise ManagementDeniedError("Current planning target revision differs")
    decision = await session.get(ManagementOwnerDecision, (scope.company_id, head.decision_id))
    current = await session.get(
        ManagementPlanRevision, (scope.company_id, head.current_revision_id)
    )
    if (
        decision is None
        or current is None
        or (
            decision.owner_id,
            decision.kind,
            decision.plan_revision_id,
            decision.payload_sha256,
        )
        != (control.owner_id, "approve", current.plan_revision_id, current.sha256)
        or head.procedure_id != base.payload.procedure.procedure_id
    ):
        raise ManagementDeniedError("Planning head lacks exact native owner approval")


async def native_planning(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    action_id: UUID,
    target_id: UUID | None,
    end_us: int,
    template: PlanningProposalTemplate,
    sources: OwnerViewSources,
) -> NativePlanning:
    require_time(end_us)
    if (
        not session.in_transaction()
        or scope.company_id != template.base_plan.company_id
        or scope.principal_id != control.owner_id
    ):
        raise ManagementDeniedError("Planning read needs its actual current owner transaction")
    await require_base_plan(session, control, scope, target_id, template)
    base = template.base_plan
    child, item = base.payload.children[0], base.payload.plan.items[0]
    action = await session.get(JournalAction, action_id)
    work = await session.get(ExecutionWork, (scope.company_id, child.binding.task_id))
    effect = await session.get(EffectIntent, (scope.company_id, action_id))
    hold = await session.get(CostHold, action_id)
    task = await session.get(
        ManagementPlanTask, (scope.company_id, base.plan_revision_id, child.binding.task_id)
    )
    if action is None or work is None or effect is None or hold is None or task is None:
        raise ManagementDeniedError("Native planning result is unavailable")
    require_native_task(task, work, child, base.payload)
    if snapshot(work).registration != registration(child.binding, item, child.quota) or (
        work.workspace_id,
        work.actor_id,
        work.parent_task_id,
    ) != (
        child.binding.workspace_id,
        child.binding.actor_id,
        base.payload.procedure.binding.task_id,
    ):
        raise ManagementDeniedError("Planning work differs from the unchanged bootstrap child")
    proposal = ActionProposal.model_validate_json(action.proposal_json)
    receipt = ActionReceipt.model_validate_json(effect.receipt_json or "")
    approval = ApprovalDecision.model_validate_json(action.approval_json or "")
    if (
        action.state != ActionState.AUTHORIZED.value
        or action.consumed_at is None
        or (
            approval.company_id,
            approval.action_id,
            approval.action_hash,
            approval.action_revision,
            approval.approver_id,
            approval.decision,
        )
        != (
            scope.company_id,
            action_id,
            action.proposal_hash,
            proposal.revision,
            control.owner_id,
            "approved",
        )
        or not approval.issued_at <= action.consumed_at <= effect.created_at < approval.expires_at
    ):
        raise ManagementDeniedError("Planning intent lacks its original exact consumed approval")
    if (
        (action.company_id, action.task_id, action.trace_id, action.id, action.proposal_hash)
        != (
            scope.company_id,
            work.task_id,
            work.trace_id,
            action_id,
            action_hash(proposal),
        )
        or (
            effect.task_id,
            effect.trace_id,
            effect.run_id,
            effect.proposal_hash,
            effect.state,
            effect.attempt_kind,
        )
        != (
            work.task_id,
            work.trace_id,
            work.run_id,
            action.proposal_hash,
            "succeeded",
            "model_requests",
        )
        or (
            proposal.company_id,
            proposal.task_id,
            proposal.trace_id,
            proposal.actor_id,
            proposal.action_id,
            proposal.tool,
            proposal.tool_version,
        )
        != (
            scope.company_id,
            work.task_id,
            work.trace_id,
            work.actor_id,
            action_id,
            "model.request.v1",
            "v1",
        )
    ):
        raise ManagementDeniedError("Planning native action/intent differs")
    if (
        (
            receipt.company_id,
            receipt.task_id,
            receipt.trace_id,
            receipt.action_id,
            receipt.proposal_hash,
            receipt.outcome,
            receipt.receipt_id,
        )
        != (
            scope.company_id,
            work.task_id,
            work.trace_id,
            action_id,
            action.proposal_hash,
            "succeeded",
            uuid5(action_id, "model-receipt-v1"),
        )
        or len(receipt.artifacts) != 1
        or receipt.artifacts[0].revision != "model-result-envelope-v1"
        or scope.principal_id not in receipt.artifacts[0].allowed_principals
        or (hold.company_id, hold.task_id, hold.state)
        != (scope.company_id, work.task_id, "reconciled")
        or hold.actual_usd is None
        or work.worker_id is not None
        or work.lease_until is not None
        or work.state != "verifying"
        or work.fence <= effect.intent_fence
    ):
        raise ManagementDeniedError("Planning lacks known billing/receipt and released native work")
    brain = owner_brain_scope(scope, identity)
    resources = tuple(
        UUID(row.resource.removeprefix("brain.resource:"))
        for row in proposal.preconditions
        if row.resource.startswith("brain.resource:")
    )
    await require_resources(session, brain, resources, await db_clock(session))
    refs = []
    for condition in proposal.preconditions:
        if not condition.resource.startswith("brain.source:"):
            continue
        require_time(end_us)
        source_id = UUID(condition.resource.removeprefix("brain.source:"))
        head = await session.get(BrainSourceHead, (scope.company_id, source_id))
        if (
            head is None
            or condition.revision != f"head:{head.generation}:{head.current_revision_id}"
        ):
            raise ManagementDeniedError("Original planning source head changed")
        revision = await session.get(
            BrainSourceRevision, (scope.company_id, head.current_revision_id)
        )
        if revision is None or revision.source_id != source_id:
            raise ManagementDeniedError("Planning source revision is unavailable")
        refs.append(await source_artifact_reference(session, brain, revision.artifact_revision_id))
    disclosure = await source_disclosure(session, control, scope, identity, sources, tuple(refs))
    if disclosure is None or not disclosure.permits(await db_clock(session)):
        raise ManagementDeniedError("Current owner source READ is unavailable")
    require_time(end_us)
    return NativePlanning(proposal, receipt, effect.created_at, hold.actual_usd)
