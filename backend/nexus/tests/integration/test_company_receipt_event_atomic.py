"""Real receipt/event/cost writes share one transaction, including final lease expiry."""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.event_models import BrainEvent
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.harness.journal_models import CostHold
from nexus.tests.generated_artifact_fixture import generated_scenario
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.receipt_atomic_support import (
    ObservedReceiptPublisher,
    failed_receipt,
    managed_effects,
)
from nexus.tests.receipt_event_support import receipt_factory as receipt_factory


@pytest.mark.parametrize("failure", ["after_append", "lease_expiry"])
async def test_actual_receipt_hook_rejection_rolls_back_outcome_cost_and_event(
    receipt_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failure: str
) -> None:
    item = await generated_scenario(
        receipt_factory,
        tmp_path,
        production=True,
        ttl_seconds=2 if failure == "lease_expiry" else 60,
    )
    lease = item.lease
    before = await item.execution.get(lease_scope(lease), identity(ACTOR))
    publisher = ObservedReceiptPublisher(item.plans.catalog)
    publisher.reject_after_append = failure == "after_append"
    if failure == "lease_expiry":
        publisher.delay_seconds = 2.2
    with pytest.raises(ExecutionDeniedError):
        await managed_effects(receipt_factory, item, publisher).record_receipt(
            lease, identity(ACTOR), failed_receipt(item), actual_usd=Decimal(0)
        )
    assert publisher.seen
    async with runtime_transaction(
        receipt_factory, lease_scope(lease), identity(ACTOR), allow_inactive=True
    ) as (session, _, _):
        intent = await session.get(EffectIntent, (COMPANY, item.action.action_id))
        hold = await session.get(CostHold, item.action.action_id)
        assert intent is not None and intent.state == "intent" and intent.receipt_json is None
        assert hold is not None and hold.state == "held" and hold.actual_usd is None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BrainEvent)
                .where(BrainEvent.kind == "receipt_recorded")
            )
            == 0
        )
    assert (
        await item.execution.get(lease_scope(lease), identity(ACTOR))
    ).counters == before.counters
