"""Public same-session pending proposal append; caller owns current scope and company mutex."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
from nexus.harness.canonical import action_hash, canonical_action
from nexus.harness.journal_contracts import ActionRecord, LedgerScope
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.lifecycle import ActionState


async def submit_pending_locked(
    session: AsyncSession, control: CompanyControl, action: ActionProposal, scope: LedgerScope
) -> ActionRecord:
    """Preserve exact submit semantics; this creates no approval, consumption, hold or effect."""
    snapshot = canonical_action(action)
    action = ActionProposal.model_validate_json(snapshot)
    if (
        not session.in_transaction()
        or control.company_id != scope.company_id
        or (action.company_id, action.task_id, action.trace_id, action.actor_id)
        != (scope.company_id, scope.task_id, scope.trace_id, scope.principal_id)
    ):
        raise ValueError("Proposal and trusted execution scope disagree")
    if control.paused or (control.policy_version, control.price_version) != (
        action.policy_version,
        action.price_version,
    ):
        raise ValueError("Company paused or action uses stale policy/prices")
    existing = await session.scalar(
        select(JournalAction).where(
            JournalAction.company_id == scope.company_id, JournalAction.id == action.action_id
        )
    )
    if existing is not None:
        if existing.proposal_json != snapshot:
            raise ValueError("Action ID already binds another immutable proposal")
        return pending_action_record(existing)
    row = JournalAction(
        id=action.action_id,
        company_id=scope.company_id,
        task_id=scope.task_id,
        trace_id=scope.trace_id,
        proposal_json=snapshot,
        proposal_hash=action_hash(action),
        state=ActionState.AWAITING_APPROVAL.value,
        approval_json=None,
        consumed_at=None,
    )
    session.add(row)
    await session.flush()
    return pending_action_record(row)


def pending_action_record(row: JournalAction) -> ActionRecord:
    """Project an actual immutable journal row, including existing decisions on exact replay."""
    return ActionRecord(
        company_id=row.company_id,
        proposal=ActionProposal.model_validate_json(row.proposal_json),
        proposal_hash=row.proposal_hash,
        state=ActionState(row.state),
        consumed_at=row.consumed_at,
        approval=ApprovalDecision.model_validate_json(row.approval_json)
        if row.approval_json
        else None,
    )
