"""Native action/plan decision audit excludes source-bearing tool inputs and receipt bodies."""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.company.management.control_support import db_clock
from nexus.company.management.lifecycle import OwnerPlanDecision, PlanRevision, PlanRevisionRef
from nexus.company.management.owner_view_contracts import ApprovalPage, ApprovalView, OwnerViewPage
from nexus.company.management.plan_models import ManagementOwnerDecision, ManagementPlanRevision
from nexus.company.management.revision_store import plan_record
from nexus.company.management.transactions import ManagementDeniedError
from nexus.harness.authorization_models import ActionAuthority
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.lifecycle import ActionState
from nexus.harness.standing_models import StandingAuthorityGrant


def decision_record(row: ManagementOwnerDecision, plan: PlanRevisionRef) -> OwnerPlanDecision:
    if (row.company_id, row.plan_revision_id, row.payload_sha256) != (
        plan.company_id,
        plan.plan_revision_id,
        plan.sha256,
    ):
        raise ManagementDeniedError("Stored owner plan decision differs")
    return OwnerPlanDecision(
        company_id=row.company_id,
        decision_id=row.decision_id,
        plan=plan,
        owner_id=row.owner_id,
        kind=cast(Literal["approve", "revoke"], row.kind),
        reason=row.reason,
        recorded_at=row.recorded_at,
    )


async def action_audit(session: AsyncSession, row: JournalAction) -> ApprovalView:
    proposal = ActionProposal.model_validate_json(row.proposal_json)
    if (
        proposal.company_id,
        proposal.task_id,
        proposal.trace_id,
        proposal.action_id,
        action_hash(proposal),
    ) != (row.company_id, row.task_id, row.trace_id, row.id, row.proposal_hash):
        raise ManagementDeniedError("Stored action decision audit differs")
    decision = (
        ApprovalDecision.model_validate_json(row.approval_json) if row.approval_json else None
    )
    if decision is not None and (
        decision.action_id,
        decision.action_hash,
        decision.action_revision,
    ) != (
        proposal.action_id,
        row.proposal_hash,
        proposal.revision,
    ):
        raise ManagementDeniedError("Owner action decision binds another exact proposal")
    grant_id = await _standing_source(session, row, proposal, decision)
    return ApprovalView(
        company_id=row.company_id,
        action_id=row.id,
        task_id=row.task_id,
        actor_id=proposal.actor_id,
        proposal_sha256=row.proposal_hash,
        tool=proposal.tool,
        tool_version=proposal.tool_version,
        resource_symbol=proposal.resource,
        estimated_cost_usd=proposal.estimated_cost_usd,
        state=ActionState(row.state),
        owner_decision=decision,
        standing_grant_id=grant_id,
        authority_observation="exact_recorded"
        if decision
        else "standing_recorded"
        if grant_id is not None
        else "pending"
        if row.consumed_at is None
        else "unavailable",
        consumed_at=row.consumed_at,
    )


async def _standing_source(
    session: AsyncSession,
    row: JournalAction,
    proposal: ActionProposal,
    decision: ApprovalDecision | None,
) -> UUID | None:
    standing = await session.get(ActionAuthority, (row.company_id, row.id))
    if standing is not None and decision is not None:
        raise ManagementDeniedError("Action audit mixes exact and standing provenance")
    grant = await session.get(StandingAuthorityGrant, (standing.grant_id)) if standing else None
    actual_grant = (
        grant is not None
        and standing is not None
        and (
            grant.company_id,
            grant.task_id,
            grant.actor_id,
            grant.snapshot_hash,
        )
        == (row.company_id, row.task_id, proposal.actor_id, standing.grant_hash)
    )
    return grant.grant_id if actual_grant and grant is not None else None


async def pending_plans(
    session: AsyncSession,
    control: CompanyControl,
    page: OwnerViewPage,
) -> tuple[tuple[PlanRevision, ...], UUID | None]:
    decided = select(ManagementOwnerDecision.plan_revision_id).where(
        ManagementOwnerDecision.company_id == control.company_id,
    )
    query = select(ManagementPlanRevision).where(
        ManagementPlanRevision.company_id == control.company_id,
        ManagementPlanRevision.plan_revision_id.not_in(decided),
    )
    if page.after_id is not None:
        query = query.where(ManagementPlanRevision.plan_revision_id > page.after_id)
    rows = tuple(
        (
            await session.scalars(
                query.order_by(ManagementPlanRevision.plan_revision_id).limit(page.limit + 1)
            )
        ).all()
    )
    return tuple(plan_record(row) for row in rows[: page.limit]), rows[
        page.limit - 1
    ].plan_revision_id if len(rows) > page.limit else None


async def approvals_page(
    session: AsyncSession,
    control: CompanyControl,
    page: OwnerViewPage,
    *,
    pending_only: bool = False,
) -> ApprovalPage:
    query = select(JournalAction).where(JournalAction.company_id == control.company_id)
    if pending_only:
        query = query.where(
            JournalAction.approval_json.is_(None),
            JournalAction.state.in_(("proposed", "awaiting_approval")),
        )
    if page.after_id is not None:
        query = query.where(JournalAction.id > page.after_id)
    rows = tuple(
        (await session.scalars(query.order_by(JournalAction.id).limit(page.limit + 1))).all()
    )
    proposals, next_plan = await pending_plans(session, control, page)
    return ApprovalPage(
        company_id=control.company_id,
        observed_at=await db_clock(session),
        approvals=tuple([await action_audit(session, row) for row in rows[: page.limit]]),
        pending_plans=proposals,
        next_after_id=rows[page.limit - 1].id if len(rows) > page.limit else None,
        next_plan_after_id=next_plan,
    )
