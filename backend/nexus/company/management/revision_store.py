"""Immutable plan proposals/owner decisions and bounded administrative revision events."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope
from nexus.company.management.acceptance_targets import current_charter, current_governance
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_support import ManagementConflictError, require_cas
from nexus.company.management.lifecycle import PlanRevision, PlanRevisionRef
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanHead,
    ManagementPlanRevision,
    ManagementProcedure,
    ManagementRevisionEvent,
)
from nexus.company.management.plans import ChildAllocation, PlanPayload
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl


def plan_record(row: ManagementPlanRevision) -> PlanRevision:
    """Reconstruct the stored immutable payload; caller projections cannot substitute for it."""
    return PlanRevision(
        company_id=row.company_id,
        plan_id=row.plan_id,
        plan_revision_id=row.plan_revision_id,
        revision=row.revision,
        sha256=row.sha256,
        payload=PlanPayload.model_validate_json(row.snapshot_json),
        proposed_by=row.proposed_by,
        recorded_at=row.recorded_at,
    )


def plan_reference(record: PlanRevision) -> PlanRevisionRef:
    """Retain the exact approved native revision/hash identity."""
    return PlanRevisionRef.model_validate_json(
        record.model_dump_json(include=set(PlanRevisionRef.model_fields))
    )


async def require_current_governance(
    session: AsyncSession,
    control: CompanyControl,
    reference: PlanRevisionRef,
    child: ChildAllocation,
) -> None:
    """Check current native goal/mandate/charter for a descriptive acceptance read."""
    row = await session.get(
        ManagementPlanRevision, (reference.company_id, reference.plan_revision_id)
    )
    if row is None:
        raise ManagementDeniedError("Acceptance plan governance is unavailable")
    payload = plan_record(row).payload
    await current_governance(session, control, payload)
    await current_charter(session, payload, child)


async def propose_locked(
    session: AsyncSession,
    scope: CompanyControlScope,
    payload: PlanPayload,
    expected: UUID | None,
    now: datetime,
) -> PlanRevision:
    """Persist a proposal without registering a root/work or replacing an operative head."""
    # This >50-line immutable revision/CAS insert preserves the operative-head rule in one flow.
    head = await session.get(ManagementPlanHead, (scope.company_id, payload.plan.plan_id))
    existing = await session.scalar(
        select(ManagementPlanRevision).where(
            ManagementPlanRevision.company_id == scope.company_id,
            ManagementPlanRevision.plan_id == payload.plan.plan_id,
            ManagementPlanRevision.revision == payload.plan.revision,
        )
    )
    digest = canonical_sha256(payload)
    if existing is not None:
        record = plan_record(existing)
        if record.sha256 != digest:
            raise ManagementConflictError("An immutable plan revision cannot be rebound")
        return record
    require_cas(head.current_revision_id if head else None, expected)
    current = (
        await session.get(ManagementPlanRevision, (scope.company_id, head.current_revision_id))
        if head
        else None
    )
    if payload.plan.revision != (current.revision + 1 if current else 1):
        raise ManagementConflictError(
            "A proposed plan needs its exact consecutive current revision"
        )
    if head is not None and head.goal_id != payload.goal.goal_id:
        raise ManagementDeniedError("A logical plan cannot change its admitted goal")
    record = PlanRevision(
        company_id=scope.company_id,
        plan_id=payload.plan.plan_id,
        plan_revision_id=uuid5(payload.plan.plan_id, f"plan:{payload.plan.revision}:{digest}"),
        revision=payload.plan.revision,
        sha256=digest,
        payload=payload,
        proposed_by=scope.principal_id,
        recorded_at=now,
    )
    session.add(
        ManagementPlanRevision(
            company_id=scope.company_id,
            plan_revision_id=record.plan_revision_id,
            plan_id=record.plan_id,
            revision=record.revision,
            goal_id=payload.goal.goal_id,
            goal_revision_id=payload.goal.revision_id,
            mandate_revision_id=payload.mandate.revision_id,
            sha256=digest,
            snapshot_json=payload.model_dump_json(by_alias=True),
            proposed_by=scope.principal_id,
            recorded_at=now,
        )
    )
    await session.flush()
    if head is None:
        session.add(
            ManagementPlanHead(
                company_id=scope.company_id,
                plan_id=record.plan_id,
                current_revision_id=record.plan_revision_id,
                goal_id=payload.goal.goal_id,
                procedure_id=None,
                decision_id=None,
                state="proposed",
            )
        )
        await session.flush()
    return record


async def decision_locked(
    session: AsyncSession,
    scope: CompanyControlScope,
    record: PlanRevision,
    kind: str,
    now: datetime,
) -> ManagementOwnerDecision:
    """Append an exact native owner decision without worker leases or fabricated effects."""
    key = uuid5(record.plan_revision_id, f"owner:{scope.principal_id}:{kind}")
    old = await session.get(ManagementOwnerDecision, (scope.company_id, key))
    if old is not None:
        if (old.plan_revision_id, old.owner_id, old.kind, old.payload_sha256) != (
            record.plan_revision_id,
            scope.principal_id,
            kind,
            record.sha256,
        ):
            raise ManagementConflictError("Owner decision identity has conflicting content")
        return old
    row = ManagementOwnerDecision(
        company_id=scope.company_id,
        decision_id=key,
        plan_revision_id=record.plan_revision_id,
        owner_id=scope.principal_id,
        kind=kind,
        payload_sha256=record.sha256,
        reason=f"Owner {kind} exact bounded management plan",
        recorded_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def consume_revision(
    session: AsyncSession,
    scope: CompanyControlScope,
    record: PlanRevision,
    procedure: ManagementProcedure,
    decision_id: UUID,
    now: datetime,
) -> None:
    """Initial approval costs zero slots; every later goal procedure approval preserves quota."""
    # Keep the >50-line previous approval, actual root counter and immutable event write together.
    previous = await session.scalar(
        select(ManagementOwnerDecision)
        .join(
            ManagementPlanRevision,
            (ManagementPlanRevision.company_id == ManagementOwnerDecision.company_id)
            & (ManagementPlanRevision.plan_revision_id == ManagementOwnerDecision.plan_revision_id),
        )
        .where(
            ManagementOwnerDecision.company_id == scope.company_id,
            ManagementOwnerDecision.kind == "approve",
            ManagementOwnerDecision.decision_id != decision_id,
            ManagementPlanRevision.goal_id == procedure.goal_id,
        )
        .order_by(
            ManagementOwnerDecision.recorded_at.desc(), ManagementOwnerDecision.decision_id.desc()
        )
        .limit(1)
    )
    if previous is None:
        return
    root = await session.get(ExecutionWork, (scope.company_id, procedure.parent_task_id))
    if root is None or root.run_id != procedure.parent_run_id:
        raise ManagementDeniedError("Actual procedure execution quota is unavailable")
    if root.plan_revisions_used + root.plan_revisions_delegated >= root.plan_revisions_limit:
        raise ManagementDeniedError("Procedure lifetime administrative revision quota is exhausted")
    root.plan_revisions_used += 1
    session.add(
        ManagementRevisionEvent(
            company_id=scope.company_id,
            event_id=uuid5(record.plan_revision_id, f"revision:{root.plan_revisions_used}"),
            procedure_id=procedure.procedure_id,
            parent_task_id=root.task_id,
            parent_run_id=root.run_id,
            previous_plan_revision_id=previous.plan_revision_id,
            next_plan_revision_id=record.plan_revision_id,
            owner_decision_id=decision_id,
            owner_id=scope.principal_id,
            revision_counter=root.plan_revisions_used,
            recorded_at=now,
        )
    )
    await session.flush()
