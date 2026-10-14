"""Exact current or historical/proposed plan inspection never fabricates native registration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.owner_view_approvals import decision_record
from nexus.company.management.owner_view_contracts import PlanView
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.owner_view_work import WorkObservation, observe_work
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanHead,
    ManagementPlanRevision,
    ManagementPlanTask,
)
from nexus.company.management.revision_store import plan_record, plan_reference
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True)
class PlanObservation:
    value: PlanView
    work: tuple[WorkObservation, ...]

    def render(self, now: datetime) -> PlanView:
        return PlanView.model_validate_json(
            self.value.model_copy(
                update={
                    "work": tuple(row.render(now) for row in self.work),
                    "observed_at": now,
                }
            ).model_dump_json()
        )


async def selected_revision(
    session: AsyncSession,
    company_id: UUID,
    plan_id: UUID,
    revision_id: UUID | None,
) -> tuple[ManagementPlanRevision, ManagementPlanHead]:
    head = await session.get(ManagementPlanHead, (company_id, plan_id))
    if head is None:
        raise ManagementDeniedError("Owner plan is unavailable")
    row = await session.get(
        ManagementPlanRevision, (company_id, revision_id or head.current_revision_id)
    )
    if row is None or row.plan_id != plan_id:
        raise ManagementDeniedError("Exact owner plan revision is unavailable")
    return row, head


async def observe_plan(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    row: ManagementPlanRevision,
    head: ManagementPlanHead,
    sources: OwnerViewSources | None,
    now: datetime,
) -> PlanObservation:
    record = plan_record(row)
    reference = plan_reference(record)
    current = head.current_revision_id == row.plan_revision_id
    query = select(ManagementOwnerDecision).where(
        ManagementOwnerDecision.company_id == scope.company_id,
        ManagementOwnerDecision.plan_revision_id == row.plan_revision_id,
    )
    if current:
        query = query.where(ManagementOwnerDecision.decision_id == head.decision_id)
    decision = await session.scalar(
        query.order_by(
            ManagementOwnerDecision.recorded_at.desc(), ManagementOwnerDecision.decision_id.desc()
        ).limit(1)
    )
    owner = decision_record(decision, reference) if decision else None
    state: Literal["proposed", "approved", "revoked"] = (
        "approved" if owner and owner.kind == "approve" else "revoked" if owner else "proposed"
    )
    if current and state != head.state:
        raise ManagementDeniedError("Plan head state differs from its actual owner decision")
    observations = await plan_work(session, control, scope, identity, row, sources)
    return PlanObservation(
        PlanView(
            company_id=scope.company_id,
            reference=reference,
            state=state,
            is_current_head=current,
            declaration=record.payload,
            decision=owner,
            observed_at=now,
            work=tuple(value.value for value in observations),
        ),
        observations,
    )


async def plan_work(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    row: ManagementPlanRevision,
    sources: OwnerViewSources | None,
) -> tuple[WorkObservation, ...]:
    tasks = tuple(
        (
            await session.scalars(
                select(ManagementPlanTask.task_id)
                .where(
                    ManagementPlanTask.company_id == scope.company_id,
                    ManagementPlanTask.plan_revision_id == row.plan_revision_id,
                )
                .order_by(ManagementPlanTask.task_id)
                .limit(101)
            )
        ).all()
    )
    if len(tasks) > 100:
        raise ManagementDeniedError("Plan registered work exceeds its declaration bound")
    observed = []
    for task_id in tasks:
        work = await session.get(ExecutionWork, (scope.company_id, task_id))
        if work is None:
            raise ManagementDeniedError("Plan native work is unavailable")
        observed.append(await observe_work(session, control, scope, identity, work, sources))
    return tuple(observed)
