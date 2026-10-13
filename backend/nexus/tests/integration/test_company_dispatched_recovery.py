"""Actual immutable-dispatch recovery keeps its segment and creates a fresh fence."""

from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.execution.runtime_store import next_segment_id
from nexus.harness.journal_models import CostHold
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, TASK, TRACE, WORKSPACE
from nexus.tests.integration.test_company_execution_store import (
    RUN,
    WORKER,
    action,
    expire_lease,
    identity,
    ready,
    receipt,
    scope,
)
from nexus.tests.integration.test_company_execution_store import (
    execution_factory as execution_factory,
)


async def dispatch(
    factory: async_sessionmaker[AsyncSession], action_id: UUID, segment_id: UUID
) -> SegmentCommand:
    """Insert only an already-authorized immutable fixture dispatch in this private DB."""
    command = SegmentCommand(
        company_id=COMPANY,
        task_id=TASK,
        trace_id=TRACE,
        actor_id=ACTOR,
        workspace_id=WORKSPACE,
        run_id=RUN,
        action_id=action_id,
        segment_id=segment_id,
    )
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        session.add(
            SegmentDispatch(
                company_id=COMPANY,
                action_id=action_id,
                task_id=TASK,
                run_id=RUN,
                segment_id=segment_id,
                workflow_id=command.workflow_id,
                binding_json=command.model_dump_json(),
            )
        )
    return command


async def test_dispatched_recovery_reuses_segment_but_fences_old_worker_and_intent(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, effects = await ready(execution_factory)
    approved = await action(execution_factory)
    segment_id = next_segment_id(await execution.get(scope(), identity()))
    await dispatch(execution_factory, approved.action_id, segment_id)
    old = await execution.recover_dispatched(scope(), identity(), WORKER, segment_id)
    await effects.begin(old, identity(), approved.action_id)
    with pytest.raises(ExecutionDeniedError):
        await execution.recover_dispatched(scope(), identity(), UUID(int=160), segment_id)
    await expire_lease()
    recovered = await execution.recover_dispatched(scope(), identity(), UUID(int=160), segment_id)
    assert recovered.segment_id == old.segment_id and recovered.run_id == old.run_id
    assert recovered.fence > old.fence and recovered.mode == "reconcile"
    assert (await execution.get(scope(), identity())).segment_number == 1
    assert (await effects.get(recovered, identity(), approved.action_id)).state == "outcome_unknown"
    async with execution_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        held = await session.get(CostHold, approved.action_id)
        assert held is not None and held.state == "unknown" and held.amount_usd > 0
    with pytest.raises(ExecutionDeniedError):
        await effects.record_receipt(old, identity(), receipt(approved))


async def test_released_known_receipt_replays_original_dispatch_without_an_extra_attempt(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, effects = await ready(execution_factory)
    approved = await action(execution_factory)
    segment_id = next_segment_id(await execution.get(scope(), identity()))
    await dispatch(execution_factory, approved.action_id, segment_id)
    old = await execution.recover_dispatched(scope(), identity(), WORKER, segment_id)
    await effects.begin(old, identity(), approved.action_id)
    await effects.record_receipt(old, identity(), receipt(approved))
    released = await execution.release(old, identity())
    assert released.worker_id is None and released.state == "verifying"
    recovered = await execution.recover_dispatched(scope(), identity(), UUID(int=161), segment_id)
    assert recovered.mode == "reconcile" and recovered.segment_id == old.segment_id
    assert (await effects.get(recovered, identity(), approved.action_id)).state == "succeeded"
    assert (await execution.get(scope(), identity())).counters.tool_attempts == 1
    with pytest.raises(ExecutionDeniedError):
        await execution.release(old, identity())


async def test_missing_dispatch_cannot_be_minted_by_a_recovery_request(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, _ = await ready(execution_factory)
    with pytest.raises(ExecutionDeniedError):
        await execution.recover_dispatched(
            scope(), identity(), WORKER, next_segment_id(await execution.get(scope(), identity()))
        )
