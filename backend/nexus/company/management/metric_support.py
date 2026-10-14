"""Resolve exact current native owner selection; no caller verdict or work permission."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_support import ManagementConflictError
from nexus.company.management.goals import GoalDefinition, GoalMetric, GoalRevisionRef
from nexus.company.management.governance_models import ManagementGoalHead, ManagementGoalRevision
from nexus.company.management.metric_contracts import MetricObservationRequest
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.revision_store import (
    plan_record,
    plan_reference,
    require_current_governance,
)
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest, snapshot
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True)
class SelectedMetricWork:
    native: ExecutionWork
    binding: CurrentPlanBinding


@dataclass(frozen=True)
class MetricSelection:
    metric: GoalMetric
    work: tuple[SelectedMetricWork, ...]


async def metric_definition(
    session: AsyncSession,
    request: MetricObservationRequest,
) -> GoalMetric:
    head = await session.get(ManagementGoalHead, (request.company_id, request.goal.goal_id))
    row = await session.get(ManagementGoalRevision, (request.company_id, request.goal.revision_id))
    if (
        head is None
        or row is None
        or not head.active
        or head.current_revision_id != row.revision_id
    ):
        raise ManagementConflictError("Current metric goal is unavailable")
    data = GoalDefinition.model_validate_json(row.payload_json)
    actual = GoalRevisionRef(
        company_id=row.company_id,
        goal_id=row.goal_id,
        revision_id=row.revision_id,
        version=row.version,
        sha256=row.sha256,
    )
    if actual != request.goal or canonical_sha256(data) != row.sha256:
        raise ManagementConflictError("Exact metric goal revision differs")
    metric = next((value for value in data.metrics if value.metric_id == request.metric_id), None)
    if metric is None:
        raise ManagementConflictError("Declared metric is unavailable")
    return metric


async def selected_metric(
    session: AsyncSession,
    control: CompanyControl,
    request: MetricObservationRequest,
) -> MetricSelection:
    metric = await metric_definition(session, request)
    row = await session.get(
        ManagementPlanRevision, (request.company_id, request.plan.plan_revision_id)
    )
    if row is None:
        raise ManagementConflictError("Selected native metric plan is unavailable")
    record = plan_record(row)
    if plan_reference(record) != request.plan or record.payload.goal != request.goal:
        raise ManagementConflictError("Metric plan binds another exact goal revision")
    values = tuple(
        [await selected_work(session, control, request, task) for task in request.task_ids]
    )
    return MetricSelection(metric, values)


async def selected_work(
    session: AsyncSession,
    control: CompanyControl,
    request: MetricObservationRequest,
    task_id: UUID,
) -> SelectedMetricWork:
    work = await session.get(ExecutionWork, (request.company_id, task_id))
    binding = await ManagementPlanStore.current_binding(session, request.company_id, task_id)
    if work is None or binding is None or binding.plan != request.plan:
        raise ManagementConflictError("Selected native metric work is unavailable")
    if binding.work.goal_id != request.goal.goal_id or (
        binding.work_sha256 != work.registration_hash
        or registration_digest(snapshot(work).registration) != work.registration_hash
    ):
        raise ManagementConflictError("Selected native metric registration differs")
    await require_current_governance(session, control, binding.plan, binding.child)
    return SelectedMetricWork(work, binding)
