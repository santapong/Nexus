"""Closed unissued planning-prefix recovery; never a lease, approval or effect permit."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.base import BrainReadScope
from nexus.company.management.planning_prepared_contracts import prepared_reference
from nexus.company.management.plans import RunBinding
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_support import KINDS, db_now, snapshot
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import ActionRecord, LedgerScope
from nexus.harness.journal_models import CompanyControl, CostHold, JournalAction
from nexus.harness.journal_submission import pending_action_record

if TYPE_CHECKING:
    from nexus.execution.planning_preparation_recovery import (
        PreparedWaitRecovery,
        RecoveredPlanningWait,
    )
    from nexus.execution.runtime_store import ExecutionStore


def recovery_scope(binding: RunBinding, action_id: UUID) -> BrainReadScope:
    """Derive the exact original configured actor scope, never an owner substitute."""
    return BrainReadScope(
        company_id=binding.company_id,
        workspace_id=binding.workspace_id,
        principal_id=binding.actor_id,
        actor_id=binding.actor_id,
        task_id=binding.task_id,
        task_trace_id=binding.trace_id,
        trace_id=binding.trace_id,
        operation_id=uuid5(action_id, "prepared-wait-recovery:v1"),
    )


def recovery_ledger(scope: BrainReadScope) -> LedgerScope:
    """Data-only scope conversion; the native wrapper still validates actual membership/work."""
    if scope.task_id is None or scope.task_trace_id is None or scope.actor_id != scope.principal_id:
        raise ExecutionDeniedError("Recovery actor scope is not its registered work")
    return LedgerScope(
        company_id=scope.company_id,
        principal_id=scope.principal_id,
        task_id=scope.task_id,
        trace_id=scope.task_trace_id,
    )


async def require_unissued_pending(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    action_id: UUID,
    expected_hash: str,
    now: datetime,
) -> ActionRecord:
    """Require one actual pending prefix with no issued or delegated lifetime history."""
    # Keep the complete native zero-issued/state/decision proof adjacent (>50 lines).
    value = snapshot(work)
    if (
        not session.in_transaction()
        or control.company_id != work.company_id
        or control.paused
        or (work.workflow_name, work.workflow_version) != ("company.planning.v1", "v1")
        or work.state not in {"running", "blocked", "awaiting_approval"}
        or value.fence < 1
        or value.segment_number < 1
        or value.segment_id is None
        or value.segment_id
        != uuid5(work.run_id, f"nexus-execution-segment-v1:{value.segment_number}")
        or any(
            getattr(work, f"{kind}_{suffix}") != 0
            for kind in KINDS
            for suffix in ("used", "delegated")
        )
    ):
        raise ExecutionDeniedError("Unissued planning preparation prefix is unavailable")
    metadata = (work.worker_id, work.lease_until, work.lease_mode, work.lease_principal_id)
    if any(item is not None for item in metadata) and (
        work.worker_id is None
        or work.lease_until is None
        or work.lease_until > now
        or work.lease_mode != "execute"
        or work.lease_principal_id != work.actor_id
    ):
        raise ExecutionDeniedError("Live or incomplete planning lease cannot be recovered")
    if work.state == "awaiting_approval":
        if any(item is not None for item in metadata) or work.waiting_action_id != action_id:
            raise ExecutionDeniedError("Existing owner wait differs from the exact action")
    elif work.waiting_action_id is not None:
        raise ExecutionDeniedError("Preparation prefix already binds another wait")
    actions = tuple(
        (
            await session.scalars(
                select(JournalAction)
                .where(
                    JournalAction.company_id == work.company_id,
                    JournalAction.task_id == work.task_id,
                )
                .limit(2)
            )
        ).all()
    )
    if len(actions) != 1:
        raise ExecutionDeniedError("Recovery requires the single original pending action")
    row = actions[0]
    record = pending_action_record(row)
    proposal = record.proposal
    if (
        (row.company_id, row.task_id, row.trace_id, row.id, row.state)
        != (work.company_id, work.task_id, work.trace_id, action_id, "awaiting_approval")
        or row.consumed_at is not None
        or record.proposal_hash != expected_hash
        or action_hash(proposal) != expected_hash
        or (proposal.company_id, proposal.task_id, proposal.trace_id, proposal.actor_id)
        != (work.company_id, work.task_id, work.trace_id, work.actor_id)
        or (proposal.tool, proposal.tool_version) != ("model.request.v1", "v1")
        or (proposal.policy_version, proposal.price_version)
        != (control.policy_version, control.price_version)
    ):
        raise ExecutionDeniedError("Original planning action or policy binding changed")
    prepared_reference(proposal)
    decision = record.approval
    if decision is not None and (
        (
            decision.company_id,
            decision.action_id,
            decision.action_revision,
            decision.action_hash,
            decision.approver_id,
            decision.decision,
        )
        != (
            work.company_id,
            action_id,
            proposal.revision,
            expected_hash,
            control.owner_id,
            "approved",
        )
        or not decision.issued_at <= now < decision.expires_at
    ):
        raise ExecutionDeniedError("Original planning decision is expired, rejected or changed")
    for model in (ExecutionAttempt, EffectIntent, CostHold, SegmentDispatch):
        if (
            await session.scalar(
                select(model)
                .where(model.company_id == work.company_id, model.task_id == work.task_id)
                .limit(1)
            )
            is not None
        ):
            raise ExecutionDeniedError("Issued, held or dispatched work cannot regain owner wait")
    return record


async def restore_wait_locked(
    store: ExecutionStore,
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    check: PreparedWaitRecovery,
) -> RecoveredPlanningWait:
    """Only this concrete original source/identity check can restore this zero-issued prefix."""
    from nexus.execution.planning_preparation_recovery import PreparedWaitRecovery

    if type(check) is not PreparedWaitRecovery or check.services.execution is not store:
        raise ExecutionDeniedError("Prepared wait recovery requires its original concrete check")
    check.require_current()
    original = snapshot(work)
    if original != check.initial:
        raise ExecutionDeniedError("Planning native snapshot changed before recovery")
    record = await require_unissued_pending(
        session,
        control,
        work,
        check.action.proposal.action_id,
        check.action.proposal_hash,
        await db_now(session),
    )
    quote = await check.validate_locked(session, control, work, record)
    if record != check.action or snapshot(work) != original:
        raise ExecutionDeniedError("Planning prefix changed during source validation")
    check.require_current()
    if work.state != "awaiting_approval":
        work.state, work.waiting_action_id = "awaiting_approval", record.proposal.action_id
        work.fence += 1
        work.worker_id = work.lease_until = work.lease_mode = work.lease_principal_id = None
        await session.flush()
    check.require_current()
    target = snapshot(work)
    final = await require_unissued_pending(
        session,
        control,
        work,
        record.proposal.action_id,
        record.proposal_hash,
        await db_now(session),
    )
    quote = await check.validate_locked(session, control, work, final)
    if final != record or snapshot(work) != target:
        raise ExecutionDeniedError("Recovered planning prefix changed before commit")
    check.require_current()
    return check.describe(final, target, quote)
