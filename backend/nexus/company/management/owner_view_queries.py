"""Bounded native head queries do not replace permission checks or owner decisions."""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.management.control_support import charter_record, mandate_record
from nexus.company.management.governance_models import (
    ManagementCharterHead,
    ManagementCharterRevision,
    ManagementGoalHead,
    ManagementGoalRevision,
    ManagementMandateHead,
    ManagementMandateRevision,
)
from nexus.company.management.operation_models import (
    ManagementCommitmentHead,
    ManagementCommitmentRevision,
)
from nexus.company.management.owner_view_approvals import decision_record
from nexus.company.management.owner_view_contracts import (
    CharterView,
    MandateView,
    OwnerViewPage,
    PlanHeadView,
)
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanHead,
    ManagementPlanRevision,
)
from nexus.company.management.revision_store import plan_record, plan_reference
from nexus.company.management.transactions import ManagementDeniedError


async def mandate_view(session: AsyncSession, company_id: UUID) -> MandateView | None:
    head = await session.get(ManagementMandateHead, company_id)
    row = (
        await session.get(ManagementMandateRevision, (company_id, head.current_revision_id))
        if head
        else None
    )
    return MandateView(active=head.active, revision=mandate_record(row)) if head and row else None


async def charter_page(
    session: AsyncSession,
    company_id: UUID,
    page: OwnerViewPage,
) -> tuple[tuple[CharterView, ...], UUID | None]:
    query = select(ManagementCharterHead).where(ManagementCharterHead.company_id == company_id)
    if page.after_id is not None:
        query = query.where(ManagementCharterHead.department_id > page.after_id)
    heads = tuple(
        (
            await session.scalars(
                query.order_by(ManagementCharterHead.department_id).limit(page.limit + 1)
            )
        ).all()
    )
    values = []
    for head in heads[: page.limit]:
        row = await session.get(ManagementCharterRevision, (company_id, head.current_revision_id))
        if row is None:
            raise ManagementDeniedError("Native charter head is unavailable")
        values.append(CharterView(active=head.active, revision=await charter_record(session, row)))
    return tuple(values), heads[page.limit - 1].department_id if len(heads) > page.limit else None


async def goal_page(
    session: AsyncSession,
    company_id: UUID,
    page: OwnerViewPage,
) -> tuple[tuple[tuple[ManagementGoalRevision, bool], ...], UUID | None]:
    query = select(ManagementGoalHead).where(ManagementGoalHead.company_id == company_id)
    if page.after_id is not None:
        query = query.where(ManagementGoalHead.goal_id > page.after_id)
    heads = tuple(
        (
            await session.scalars(query.order_by(ManagementGoalHead.goal_id).limit(page.limit + 1))
        ).all()
    )
    values = []
    for head in heads[: page.limit]:
        row = await session.get(ManagementGoalRevision, (company_id, head.current_revision_id))
        if row is None:
            raise ManagementDeniedError("Native goal head is unavailable")
        values.append((row, head.active))
    return tuple(values), heads[page.limit - 1].goal_id if len(heads) > page.limit else None


async def plan_head_view(session: AsyncSession, head: ManagementPlanHead) -> PlanHeadView:
    row = await session.get(ManagementPlanRevision, (head.company_id, head.current_revision_id))
    if row is None:
        raise ManagementDeniedError("Native plan head is unavailable")
    record = plan_record(row)
    reference = plan_reference(record)
    decision = (
        await session.get(ManagementOwnerDecision, (head.company_id, head.decision_id))
        if head.decision_id
        else None
    )
    if head.state != "proposed" and decision is None:
        raise ManagementDeniedError("Native operative plan decision is unavailable")
    return PlanHeadView(
        reference=reference,
        goal=record.payload.goal,
        state=cast(Literal["proposed", "approved", "revoked"], head.state),
        decision=decision_record(decision, reference) if decision else None,
    )


async def plan_page(
    session: AsyncSession,
    company_id: UUID,
    page: OwnerViewPage,
) -> tuple[tuple[PlanHeadView, ...], UUID | None]:
    query = select(ManagementPlanHead).where(ManagementPlanHead.company_id == company_id)
    if page.after_id is not None:
        query = query.where(ManagementPlanHead.plan_id > page.after_id)
    heads = tuple(
        (
            await session.scalars(query.order_by(ManagementPlanHead.plan_id).limit(page.limit + 1))
        ).all()
    )
    return tuple([await plan_head_view(session, head) for head in heads[: page.limit]]), heads[
        page.limit - 1
    ].plan_id if len(heads) > page.limit else None


async def commitment_page(
    session: AsyncSession,
    company_id: UUID,
    page: OwnerViewPage,
) -> tuple[tuple[ManagementCommitmentRevision, ...], UUID | None]:
    query = select(ManagementCommitmentHead).where(
        ManagementCommitmentHead.company_id == company_id
    )
    if page.after_id is not None:
        query = query.where(ManagementCommitmentHead.commitment_id > page.after_id)
    heads = tuple(
        (
            await session.scalars(
                query.order_by(ManagementCommitmentHead.commitment_id).limit(page.limit + 1)
            )
        ).all()
    )
    values = []
    for head in heads[: page.limit]:
        row = await session.get(
            ManagementCommitmentRevision, (company_id, head.current_revision_id)
        )
        if row is None:
            raise ManagementDeniedError("Native commitment head is unavailable")
        values.append(row)
    return tuple(values), heads[page.limit - 1].commitment_id if len(heads) > page.limit else None
