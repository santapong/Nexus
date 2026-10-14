"""Current native approved plan/goal/work boundaries for owner commitment declarations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.commitment_contracts import CommitmentRevision
from nexus.company.management.control_support import current_mandate, require_member
from nexus.company.management.goals import GoalDefinition, GoalRevisionRef
from nexus.company.management.governance_models import ManagementGoalHead, ManagementGoalRevision
from nexus.company.management.operation_models import ManagementCommitmentRevision
from nexus.company.management.operations import CommitmentDefinition
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.revision_store import plan_record, plan_reference
from nexus.company.management.transactions import ManagementDeniedError
from nexus.harness.journal_models import CompanyControl


def commitment_record(row: ManagementCommitmentRevision) -> CommitmentRevision:
    definition = CommitmentDefinition.model_validate_json(row.payload_json)
    if (
        definition.goal.goal_id,
        definition.goal.revision_id,
        definition.plan.plan_revision_id,
        definition.responsible_id,
        definition.due.actionable_at,
    ) != (
        row.goal_id,
        row.goal_revision_id,
        row.plan_revision_id,
        row.responsible_id,
        row.actionable_at,
    ):
        raise ManagementDeniedError("Stored commitment native bindings differ")
    return CommitmentRevision(
        company_id=row.company_id,
        commitment_id=row.commitment_id,
        revision_id=row.revision_id,
        version=row.version,
        sha256=row.sha256,
        definition=definition,
        recorded_by=row.recorded_by,
        recorded_at=row.recorded_at,
    )


async def require_commitment_binding(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    definition: CommitmentDefinition,
) -> None:
    if definition.company_id != scope.company_id:
        raise ManagementDeniedError("Commitment company is unavailable")
    head = await session.get(ManagementGoalHead, (scope.company_id, definition.goal.goal_id))
    goal = await session.get(
        ManagementGoalRevision, (scope.company_id, definition.goal.revision_id)
    )
    if (
        head is None
        or goal is None
        or not head.active
        or head.current_revision_id != goal.revision_id
    ):
        raise ManagementDeniedError("Commitment needs its current active goal")
    reference = GoalRevisionRef(
        company_id=goal.company_id,
        goal_id=goal.goal_id,
        revision_id=goal.revision_id,
        version=goal.version,
        sha256=goal.sha256,
    )
    if reference != definition.goal:
        raise ManagementDeniedError("Commitment goal reference differs")
    data = GoalDefinition.model_validate_json(goal.payload_json)
    if (data.company_id, data.goal_id, canonical_sha256(data)) != (
        scope.company_id,
        goal.goal_id,
        goal.sha256,
    ):
        raise ManagementDeniedError("Commitment goal native hash differs")
    await current_mandate(session, scope, data.mandate)
    await require_member(session, control, definition.responsible_id)
    native = await session.get(
        ManagementPlanRevision, (scope.company_id, definition.plan.plan_revision_id)
    )
    if native is None:
        raise ManagementDeniedError("Commitment plan is unavailable")
    record = plan_record(native)
    if plan_reference(record) != definition.plan or record.payload.goal != definition.goal:
        raise ManagementDeniedError("Commitment plan belongs to another exact goal")
    for work in definition.work:
        binding = await ManagementPlanStore.current_binding(session, scope.company_id, work.task_id)
        if binding is None or binding.plan != definition.plan or binding.child.binding != work:
            raise ManagementDeniedError("Commitment needs exact current approved native work")
        await require_member(session, control, work.actor_id)
