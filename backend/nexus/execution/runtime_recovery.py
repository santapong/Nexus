"""Recover only an immutable dispatched segment; never reinterpret cached permits."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.management.cancellation_support import require_not_cancelled
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_store import _unresolved, _waiting_authorized, next_segment_id
from nexus.execution.runtime_support import (
    db_now,
    mark_unknown_intents,
    require_runtime_scope,
    snapshot,
)
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl


async def dispatched_binding(
    session: AsyncSession,
    row: ExecutionWork,
    scope: LedgerScope,
    segment_id: UUID,
) -> SegmentCommand:
    """Validate permanent dispatch columns and canonical command against registered work."""
    dispatch = await session.scalar(
        select(SegmentDispatch).where(
            SegmentDispatch.company_id == row.company_id,
            SegmentDispatch.task_id == row.task_id,
            SegmentDispatch.run_id == row.run_id,
            SegmentDispatch.segment_id == segment_id,
        )
    )
    if dispatch is None:
        raise ExecutionDeniedError("Recovery requires an immutable existing dispatch")
    command = SegmentCommand.model_validate_json(dispatch.binding_json)
    command.require_scope(scope)
    if (
        command.company_id,
        command.task_id,
        command.trace_id,
        command.actor_id,
        command.workspace_id,
        command.run_id,
        command.action_id,
        command.segment_id,
        command.workflow_id,
        command.model_dump_json(),
    ) != (
        row.company_id,
        row.task_id,
        row.trace_id,
        row.actor_id,
        row.workspace_id,
        row.run_id,
        dispatch.action_id,
        dispatch.segment_id,
        dispatch.workflow_id,
        dispatch.binding_json,
    ):
        raise ExecutionDeniedError("Dispatched recovery binding differs from registered execution")
    snapshot(row)
    return command


async def recover_locked(
    session: AsyncSession,
    control: CompanyControl,
    row: ExecutionWork,
    scope: LedgerScope,
    identity: VerifiedIdentity,
    worker_id: UUID,
    segment_id: UUID,
    duration: timedelta,
) -> ExecutionWork:
    """New fence for the same issued segment; fresh work alone advances its sequence.

    This function's state transition is kept together so binding, orphan intent,
    eligibility, mode and fence commit under one company-first transaction.
    """
    command = await dispatched_binding(session, row, scope, segment_id)
    now = await db_now(session)
    if row.worker_id is not None and row.lease_until is not None and row.lease_until > now:
        raise ExecutionDeniedError("Dispatched segment still has a live lease")
    same_segment = row.segment_id == segment_id
    if not same_segment and segment_id != next_segment_id(snapshot(row)):
        raise ExecutionDeniedError(
            "Dispatch is older or differently sequenced than persistent execution"
        )
    unresolved = await _unresolved(session, row)
    known = await session.get(EffectIntent, (row.company_id, command.action_id))
    issued = bool(unresolved or known is not None)
    if not same_segment and issued:
        raise ExecutionDeniedError("A fresh segment cannot inherit unresolved issued effects")
    if not issued:
        await require_not_cancelled(session, row.company_id, row.task_id)
        await require_runtime_scope(
            session, control, scope, identity, allow_inactive=False, owner_read=False
        )
        if control.paused:
            raise ExecutionDeniedError("Paused company cannot start a fresh dispatched effect")
        if row.state == "awaiting_approval":
            await _waiting_authorized(session, row)
        elif row.state not in {"eligible", "running"}:
            raise ExecutionDeniedError("Dispatched work is not eligible for new execution")
    await mark_unknown_intents(session, row, unresolved)
    if unresolved:
        row.state = "outcome_unknown"
    elif not issued:
        row.state, row.waiting_action_id = "running", None
    row.fence += 1
    if not same_segment:
        row.segment_number += 1
    row.segment_id, row.worker_id = segment_id, worker_id
    row.lease_principal_id = row.actor_id
    row.lease_until, row.lease_mode = now + duration, "reconcile" if issued else "execute"
    await session.flush()
    return row


async def release_locked(
    session: AsyncSession, row: ExecutionWork, *, blocked: bool = False
) -> None:
    """Release capacity while preserving recorded facts and marking unfinished intent unknown."""
    unresolved = await _unresolved(session, row)
    await mark_unknown_intents(session, row, unresolved)
    if unresolved:
        row.state = "outcome_unknown"
    elif blocked:
        row.state = "blocked"
    row.fence += 1
    row.worker_id = row.lease_until = row.lease_mode = row.lease_principal_id = None
    await session.flush()
