"""Original logical attempt/fence/positive hold conservation from actual-shaped native records."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.contracts.actions import ActionProposal
from nexus.company.strategy.publication_intent import require_strategy_intent_locked
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CostHold, JournalAction


def intent_records() -> tuple[
    MagicMock,
    ExecutionWork,
    ActionProposal,
    JournalAction,
    EffectIntent,
    ExecutionAttempt,
    CostHold,
]:
    # This >50-line fixture binds the three original native records and positive unknown money.
    now = datetime.now(UTC)
    action = ActionProposal(
        company_id=UUID(int=1),
        action_id=UUID(int=2),
        task_id=UUID(int=3),
        trace_id=UUID(int=4),
        actor_id=UUID(int=5),
        revision=1,
        tool="company.cycle-artifact.write.v1",
        tool_version="v1",
        resource="strategy.output",
        parameters={},
        policy_version="p1",
        price_version="p1",
        estimated_cost_usd=Decimal(".01"),
    )
    work = ExecutionWork(
        company_id=action.company_id,
        task_id=action.task_id,
        trace_id=action.trace_id,
        run_id=UUID(int=6),
        fence=4,
    )
    record = JournalAction(
        id=action.action_id,
        proposal_hash=action_hash(action),
        consumed_at=now - timedelta(seconds=3),
    )
    effect = EffectIntent(
        company_id=action.company_id,
        action_id=action.action_id,
        task_id=action.task_id,
        trace_id=action.trace_id,
        run_id=work.run_id,
        proposal_hash=record.proposal_hash,
        attempt_kind="tool_attempts",
        intent_fence=1,
        created_at=now - timedelta(seconds=1),
    )
    attempt = ExecutionAttempt(
        company_id=action.company_id,
        task_id=action.task_id,
        trace_id=action.trace_id,
        attempt_id=action.action_id,
        kind="tool_attempts",
        fence=1,
        reserved_at=now - timedelta(seconds=2),
    )
    hold = CostHold(
        company_id=action.company_id,
        action_id=action.action_id,
        task_id=action.task_id,
        amount_usd=Decimal(".01"),
        state="unknown",
        actual_usd=None,
    )
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(side_effect=[effect, attempt, hold])
    return session, work, action, record, effect, attempt, hold


async def test_known_original_intent_does_not_rewrite_fence_attempt_or_unknown_money() -> None:
    session, work, action, record, effect, attempt, hold = intent_records()
    assert await require_strategy_intent_locked(session, work, action, record) is effect
    assert effect.intent_fence == attempt.fence == 1 and work.fence == 4
    assert hold.state == "unknown" and hold.actual_usd is None and hold.amount_usd == Decimal(".01")
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.parametrize(
    "variant",
    [
        "run",
        "proposal",
        "fence",
        "attempt_kind",
        "attempt_fence",
        "attempt_time",
        "hold_company",
        "hold_zero",
        "fake_actual",
    ],
)
async def test_spliced_original_native_basis_cannot_qualify(variant: str) -> None:
    session, work, action, record, effect, attempt, hold = intent_records()
    if variant == "run":
        effect.run_id = UUID(int=999)
    elif variant == "proposal":
        effect.proposal_hash = "a" * 64
    elif variant == "fence":
        effect.intent_fence = 5
    elif variant == "attempt_kind":
        attempt.kind = "model_requests"
    elif variant == "attempt_fence":
        attempt.fence = 2
    elif variant == "attempt_time":
        attempt.reserved_at = effect.created_at + timedelta(seconds=1)
    elif variant == "hold_company":
        hold.company_id = UUID(int=999)
    elif variant == "hold_zero":
        hold.amount_usd = Decimal("0")
    else:
        hold.actual_usd = Decimal("0")
    with pytest.raises(ValueError):
        await require_strategy_intent_locked(session, work, action, record)
