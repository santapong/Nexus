"""An actual failed bounded process creates its receipt wake without manual event append."""

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.event_models import BrainEvent
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.receipt_event_publisher import NativeReceiptEventPublisher
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt
from nexus.execution.runtime_support import lease_scope, runtime_transaction
from nexus.tests.builder_runtime_support import scenario
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.receipt_event_support import draft_store
from nexus.tests.receipt_event_support import receipt_factory as receipt_factory


async def test_actual_failed_builder_receipt_emits_once_and_publishes_owner_draft(
    receipt_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    item = await scenario(receipt_factory, tmp_path, argv=("/bin/sh", "-c", "exit 7"))
    item.runner.effects = EffectStore(
        receipt_factory,
        management_catalog=item.guard.catalog,
        management_artifacts=item.guard.artifacts,
        management_freshness=item.guard.freshness,
        receipt_events=NativeReceiptEventPublisher(item.guard.catalog),
    )
    result = await item.runner.run(item.lease, identity(ACTOR), item.action, item.spec, item.guard)
    assert result is not None and result.outcome == "commands_failed"
    before = await item.runner.execution.get(lease_scope(item.guard.lease), identity(ACTOR))
    assert (
        await item.runner.run(item.guard.lease, identity(ACTOR), item.action, item.spec, item.guard)
        == result
    )
    assert (
        await item.runner.execution.get(lease_scope(item.guard.lease), identity(ACTOR))
    ).counters == before.counters
    async with runtime_transaction(
        receipt_factory, lease_scope(item.guard.lease), identity(ACTOR)
    ) as (session, _, _):
        intent = await session.get(EffectIntent, (COMPANY, item.action.action_id))
        assert intent is not None and intent.state == "failed" and intent.receipt_json is not None
        assert await session.scalar(select(func.count()).select_from(ExecutionAttempt)) == 1
    async with management_owner_transaction(receipt_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        events = (
            await session.scalars(select(BrainEvent).where(BrainEvent.kind == "receipt_recorded"))
        ).all()
        assert len(events) == 1 and events[0].action_id == item.action.action_id
        event_id = events[0].event_id
    store = draft_store(receipt_factory, item, tmp_path)
    saved = await store.publish_event(control(), identity(OWNER), event_id)
    assert saved.signal.kind == "failed" and saved.signal.acceptance is None
    assert await store.get_current(control(), identity(OWNER), saved.draft_id) == saved
    assert await store.publish_event(control(), identity(OWNER), event_id) == saved
