"""Actual original S intent/attempt/hold facts; no new effect or money mutation."""

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CostHold, JournalAction


async def require_strategy_intent_locked(
    session: AsyncSession,
    work: ExecutionWork,
    action: ActionProposal,
    record: JournalAction,
) -> EffectIntent:
    """Bind the actual issued logical attempt and permanent positive reservation."""
    # Keep this >50-line native intent/attempt/hold consistency boundary in one read.
    effect = await session.get(EffectIntent, (work.company_id, action.action_id))
    require_acceptance(effect is not None and record.consumed_at is not None)
    assert effect is not None and record.consumed_at is not None
    require_acceptance(
        (
            effect.company_id,
            effect.action_id,
            effect.task_id,
            effect.trace_id,
            effect.run_id,
            effect.proposal_hash,
            effect.attempt_kind,
        )
        == (
            work.company_id,
            action.action_id,
            work.task_id,
            work.trace_id,
            work.run_id,
            action_hash(action),
            "tool_attempts",
        )
        and record.proposal_hash == effect.proposal_hash
        and type(effect.intent_fence) is int
        and 0 < effect.intent_fence <= work.fence
    )
    attempt = await session.get(ExecutionAttempt, (work.company_id, work.task_id, action.action_id))
    require_acceptance(attempt is not None)
    assert attempt is not None
    require_acceptance(
        (
            attempt.company_id,
            attempt.task_id,
            attempt.trace_id,
            attempt.attempt_id,
            attempt.kind,
            attempt.fence,
        )
        == (
            work.company_id,
            work.task_id,
            work.trace_id,
            action.action_id,
            "tool_attempts",
            effect.intent_fence,
        )
        and record.consumed_at <= attempt.reserved_at <= effect.created_at
    )
    hold = await session.get(CostHold, action.action_id)
    require_acceptance(hold is not None)
    assert hold is not None
    require_acceptance(
        (hold.company_id, hold.task_id, hold.amount_usd)
        == (action.company_id, action.task_id, action.estimated_cost_usd)
        and hold.amount_usd > 0
        and hold.state in {"held", "unknown", "reconciled"}
        and ((hold.state == "reconciled") == (hold.actual_usd is not None))
    )
    return effect
