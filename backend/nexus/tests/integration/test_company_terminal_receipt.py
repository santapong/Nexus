"""Failed model results preserve actual billing and blocked state in the receipt transaction."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.harness.journal_models import CostHold, WorkBudget
from nexus.tests.integration.test_company_directory import COMPANY, TASK
from nexus.tests.integration.test_company_execution_store import (
    WORKER,
    action,
    execution_factory,
    identity,
    ready,
    receipt,
    scope,
)

__all__ = ["execution_factory"]


async def test_failed_receipt_records_actual_cost_and_blocked_state_atomically(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, effects = await ready(execution_factory)
    proposal = await action(execution_factory)
    lease = await execution.claim(scope(), identity(), WORKER)
    await effects.begin(lease, identity(), proposal.action_id, kind="model_requests")
    failed = receipt(proposal, outcome="failed")
    result = await effects.record_receipt(
        lease, identity(), failed, actual_usd=Decimal("0.15"), blocked=True
    )
    assert result.state == "failed"
    current = await execution.get(scope(), identity())
    assert current.state == "blocked" and current.counters.model_requests == 1
    async with execution_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        hold = await session.get(CostHold, proposal.action_id)
        budget = await session.get(WorkBudget, (COMPANY, TASK))
        assert hold is not None and hold.actual_usd == Decimal("0.15")
        assert budget is not None and budget.held_usd == 0 and budget.spent_usd == Decimal("0.15")
    assert await effects.record_receipt(lease, identity(), failed) == result
    assert (await execution.get(scope(), identity())).state == "blocked"
    assert (await execution.release(lease, identity())).state == "blocked"


@pytest.mark.parametrize("outcome", ["succeeded", "outcome_unknown"])
async def test_only_failed_receipt_can_request_terminal_block(
    execution_factory: async_sessionmaker[AsyncSession], outcome: str
) -> None:
    execution, effects = await ready(execution_factory)
    proposal = await action(execution_factory)
    lease = await execution.claim(scope(), identity(), WORKER)
    await effects.begin(lease, identity(), proposal.action_id)
    with pytest.raises(ExecutionDeniedError):
        await effects.record_receipt(
            lease, identity(), receipt(proposal, outcome=outcome), blocked=True
        )
