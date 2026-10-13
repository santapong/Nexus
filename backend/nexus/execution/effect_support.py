"""Exact pre-effect authorization and immutable effect/result bindings."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.contracts.results import ActionReceipt, VerificationResult
from nexus.execution.runtime_contracts import (
    AttemptKind,
    EffectRecord,
    EffectState,
    ExecutionDeniedError,
)
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.authorization_source import require_action_authority
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl, CostHold, JournalAction


def effect_record(row: EffectIntent) -> EffectRecord:
    """Read application JSON only, never deserialize native SDK clients or history."""
    return EffectRecord(
        company_id=row.company_id,
        action_id=row.action_id,
        task_id=row.task_id,
        trace_id=row.trace_id,
        run_id=row.run_id,
        proposal_hash=row.proposal_hash,
        intent_fence=row.intent_fence,
        attempt_kind=cast(AttemptKind, row.attempt_kind),
        state=cast(EffectState, row.state),
        created_at=row.created_at,
        receipt=ActionReceipt.model_validate_json(row.receipt_json) if row.receipt_json else None,
        verification=VerificationResult.model_validate_json(row.verification_json)
        if row.verification_json
        else None,
    )


async def effect_row(session: AsyncSession, work: ExecutionWork, action_id: UUID) -> EffectIntent:
    row = await session.scalar(
        select(EffectIntent).where(
            EffectIntent.company_id == work.company_id,
            EffectIntent.task_id == work.task_id,
            EffectIntent.run_id == work.run_id,
            EffectIntent.action_id == action_id,
        )
    )
    if row is None:
        raise ExecutionDeniedError("Effect intent is unavailable in this logical run")
    return row


async def require_effect_authority(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    action_id: UUID,
    now: datetime,
    resources: tuple[ResourceRevision, ...],
    scope: LedgerScope,
    identity: VerifiedIdentity,
) -> JournalAction:
    """Recheck exact authority after enqueue; consumed authorization is not perpetual permission."""
    action = await session.get(JournalAction, action_id)
    hold = await session.get(CostHold, action_id)
    if (
        action is None
        or hold is None
        or (action.company_id, action.task_id, action.trace_id)
        != (
            work.company_id,
            work.task_id,
            work.trace_id,
        )
        or (hold.company_id, hold.task_id) != (work.company_id, work.task_id)
        or (action.state != "authorized" or action.consumed_at is None or hold.state != "held")
    ):
        raise ExecutionDeniedError(
            "Effect requires a committed authorized exact action and held cost"
        )
    proposal = ActionProposal.model_validate_json(action.proposal_json)
    if proposal.actor_id != work.actor_id or action_hash(proposal) != action.proposal_hash:
        raise ExecutionDeniedError("Stored action identity or digest differs from registered actor")
    try:
        await require_action_authority(session, control, action, scope, identity, now, resources)
    except ValueError as exc:
        raise ExecutionDeniedError("Current exact effect authority is stale or invalid") from exc
    return action


def require_receipt_binding(row: EffectIntent, receipt: ActionReceipt) -> None:
    if (
        receipt.company_id,
        receipt.action_id,
        receipt.task_id,
        receipt.trace_id,
        receipt.proposal_hash,
    ) != (
        row.company_id,
        row.action_id,
        row.task_id,
        row.trace_id,
        row.proposal_hash,
    ):
        raise ExecutionDeniedError("Receipt does not match the exact persisted effect intent")
