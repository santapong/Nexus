"""Existing exact M1 approval consumption/budget logic, reusable under one company mutex."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ResourceRevision
from nexus.harness.approvals import ApprovalContext, require_exact_approval
from nexus.harness.journal_budget import (
    require_registered_access,
    reserve_cost,
    reserve_registered_cost,
)
from nexus.harness.journal_contracts import ActionRecord, LedgerScope
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.journal_submission import pending_action_record
from nexus.harness.lifecycle import ActionState, require_transition


async def authorize_locked(
    session: AsyncSession,
    row: JournalAction,
    control: CompanyControl,
    scope: LedgerScope,
    now: datetime,
    resources: tuple[ResourceRevision, ...],
    *,
    registered: bool,
) -> ActionRecord:
    """Preserve M1 exact approval/own-slice reservation; caller owns current company transaction."""
    record = pending_action_record(row)
    if record.approval is None or row.consumed_at is not None:
        raise ValueError("Approval is missing or already consumed")
    context = ApprovalContext(
        company_id=scope.company_id,
        owner_id=control.owner_id,
        actor_id=scope.principal_id,
        now=now,
        policy_version=control.policy_version,
        price_version=control.price_version,
        paused=control.paused,
        resources=resources,
    )
    require_exact_approval(record.proposal, record.approval, context)
    require_transition(record.state, ActionState.AUTHORIZED)
    if registered:
        await reserve_registered_cost(session, control, record.proposal, scope, now)
    else:
        await reserve_cost(session, control, record.proposal, scope, now)
    row.consumed_at, row.state = now, ActionState.AUTHORIZED.value
    return pending_action_record(row)


async def authorize_registered_pending_locked(
    session: AsyncSession,
    control: CompanyControl,
    scope: LedgerScope,
    identity: VerifiedIdentity,
    action_id: UUID,
    now: datetime,
    resources: tuple[ResourceRevision, ...],
) -> ActionRecord:
    """Check actual registered access and consume exact approval in the caller's CC transaction."""
    if not session.in_transaction() or control.company_id != scope.company_id:
        raise ValueError("Registered authorization requires its current company transaction")
    row = await session.get(JournalAction, action_id)
    if row is None or (row.company_id, row.task_id, row.trace_id) != (
        scope.company_id,
        scope.task_id,
        scope.trace_id,
    ):
        raise ValueError("Registered authorization lacks its exact native action")
    record = pending_action_record(row)
    await require_registered_access(session, control, record.proposal, scope, identity, owner=False)
    if row.consumed_at is not None:
        if record.state != ActionState.AUTHORIZED:
            raise ValueError("Previously consumed action is not authorized")
        return record
    return await authorize_locked(session, row, control, scope, now, resources, registered=True)
