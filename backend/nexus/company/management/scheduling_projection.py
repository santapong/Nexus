"""Stable native task pages and descriptive current/historical registration projections."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.management.operations import Eligibility, EligibilityReason, EligibilityState
from nexus.company.management.plan_models import (
    ManagementPlanHead,
    ManagementPlanRevision,
    ManagementPlanTask,
)
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.plans import RunBinding
from nexus.company.management.revision_store import plan_record, plan_reference
from nexus.company.management.scheduling_contracts import ScanRequest, ScheduledWork
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import snapshot


async def task_page(
    session: AsyncSession,
    company_id: UUID,
    request: ScanRequest,
    maximum: int,
) -> tuple[tuple[ExecutionWork, ...], bool]:
    """Stable distinct native child IDs; procedure roots never enter the work queue."""
    current = select(ManagementPlanHead.current_revision_id).where(
        ManagementPlanHead.company_id == company_id
    )
    ids = select(ManagementPlanTask.task_id).where(
        ManagementPlanTask.company_id == company_id,
        ManagementPlanTask.plan_revision_id.in_(current),
    )
    query = select(ExecutionWork).where(
        ExecutionWork.company_id == company_id, ExecutionWork.task_id.in_(ids)
    )
    if request.task_ids:
        query = query.where(ExecutionWork.task_id.in_(request.task_ids))
    if request.page is not None:
        query = query.where(ExecutionWork.task_id > request.page.after_task_id)
    rows = tuple(
        (await session.scalars(query.order_by(ExecutionWork.task_id).limit(maximum + 1))).all()
    )
    return rows[:maximum], len(rows) > maximum


def projection(
    work: ExecutionWork,
    binding: CurrentPlanBinding,
    state: EligibilityState,
    reason: EligibilityReason,
) -> ScheduledWork:
    """Project validated native identity without treating the state as a permit."""
    return ScheduledWork(
        company_id=work.company_id,
        eligibility=Eligibility(
            company_id=work.company_id,
            work=binding.child.binding,
            plan=binding.plan,
            state=state,
            reason=reason,
        ),
    )


async def stale_projection(
    session: AsyncSession, work: ExecutionWork, *, cancelled: bool = False
) -> ScheduledWork:
    """Preserve an actual permanent stop even when the approved plan is no longer current."""
    row = await session.scalar(
        select(ManagementPlanRevision)
        .join(
            ManagementPlanTask,
            (ManagementPlanTask.company_id == ManagementPlanRevision.company_id)
            & (ManagementPlanTask.plan_revision_id == ManagementPlanRevision.plan_revision_id),
        )
        .where(
            ManagementPlanRevision.company_id == work.company_id,
            ManagementPlanTask.task_id == work.task_id,
        )
        .order_by(
            ManagementPlanRevision.recorded_at.desc(),
            ManagementPlanRevision.plan_revision_id.desc(),
        )
        .limit(1)
    )
    if row is None:
        raise ManagementDeniedError("Selected native management work is unavailable")
    record = snapshot(work).registration
    binding = RunBinding(
        company_id=work.company_id,
        workspace_id=work.workspace_id,
        actor_id=work.actor_id,
        task_id=work.task_id,
        trace_id=work.trace_id,
        run_id=work.run_id,
        workflow_name=record.workflow_name,
        workflow_version=record.workflow_version,
        model_profile=record.model_profile,
        model_registry_version=record.model_registry_version,
    )
    return ScheduledWork(
        company_id=work.company_id,
        eligibility=Eligibility(
            company_id=work.company_id,
            work=binding,
            plan=plan_reference(plan_record(row)),
            state="cancelled" if cancelled else "blocked",
            reason="work_cancelled" if cancelled else "versions_stale",
        ),
    )
