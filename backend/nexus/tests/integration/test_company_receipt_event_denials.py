"""Stored issuance/outcome and exact configured resource are required for receipt wakes."""

from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.event_models import BrainEvent
from nexus.company.notifications.receipt_event_publisher import NativeReceiptEventPublisher
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import db_now, execution_row, lease_scope, runtime_transaction
from nexus.harness.journal_models import CostHold
from nexus.tests.generated_artifact_fixture import generated_scenario
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.receipt_atomic_support import failed_receipt, managed_effects
from nexus.tests.receipt_event_support import receipt_factory as receipt_factory


async def test_direct_receipt_publisher_cannot_replace_actual_intent_with_transient_failed_row(
    receipt_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    item = await generated_scenario(receipt_factory, tmp_path, production=True)
    receipt = failed_receipt(item)
    with pytest.raises(ExecutionDeniedError):
        async with runtime_transaction(
            receipt_factory, lease_scope(item.lease), identity(ACTOR)
        ) as (session, control, _):
            work = await execution_row(session, lease_scope(item.lease))
            actual = await session.get(EffectIntent, (COMPANY, item.action.action_id))
            assert actual is not None
            fake = EffectIntent(
                **{
                    column.name: getattr(actual, column.name)
                    for column in cast(Table, EffectIntent.__table__).columns
                }
            )
            fake.state, fake.receipt_json = "failed", receipt.model_dump_json()
            await NativeReceiptEventPublisher(item.plans.catalog).publish(
                session, control, work, fake, receipt, identity(ACTOR), await db_now(session)
            )


@pytest.mark.parametrize("failure", ["catalog_company", "resource_symbol", "conflicting_receipt"])
async def test_receipt_wake_config_or_conflict_cannot_commit_partial_outcome(
    receipt_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failure: str
) -> None:
    from uuid import uuid4

    item = await generated_scenario(receipt_factory, tmp_path, production=True)
    receipt, catalog = failed_receipt(item), item.plans.catalog
    if failure == "catalog_company":
        catalog = catalog.model_copy(update={"company_id": uuid4()})
        # Constructor normalization independently rejects the inconsistent catalog.
        with pytest.raises(ValueError):
            NativeReceiptEventPublisher(catalog)
        return
    if failure == "resource_symbol":
        catalog = catalog.model_copy(update={"resources": ()})
    else:
        receipt = receipt.model_copy(update={"proposal_hash": "f" * 64})
    with pytest.raises(ExecutionDeniedError):
        await managed_effects(
            receipt_factory, item, NativeReceiptEventPublisher(catalog)
        ).record_receipt(item.lease, identity(ACTOR), receipt, actual_usd=Decimal(0))
    async with runtime_transaction(receipt_factory, lease_scope(item.lease), identity(ACTOR)) as (
        session,
        _,
        _,
    ):
        actual = await session.get(EffectIntent, (COMPANY, item.action.action_id))
        hold = await session.get(CostHold, item.action.action_id)
        assert actual is not None and actual.state == "intent" and actual.receipt_json is None
        assert hold is not None and hold.state == "held" and hold.actual_usd is None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BrainEvent)
                .where(BrainEvent.kind == "receipt_recorded")
            )
            == 0
        )
