"""Actual pending verifier fixture supplies approved inputs without invented execution outcomes."""

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.harness.journal_models import CostHold
from nexus.tests.engineering_fixture import engineering_scenario
from nexus.tests.engineering_pending_contracts import PendingEngineeringScenario
from nexus.tests.engineering_recovery_fixture import (
    engineering_recovery_factory as engineering_recovery_factory,
)
from nexus.tests.integration.test_company_directory import COMPANY


async def test_actual_pending_verifier_has_dispatch_hold_and_no_lease_intent_or_result(
    engineering_recovery_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    item = await engineering_scenario(
        engineering_recovery_factory, tmp_path, reserve_native_dispatch=True, defer_verifier=True
    )
    assert isinstance(item, PendingEngineeringScenario)
    job = item.verifier_spec.job
    assert not hasattr(item, "verifier") and not hasattr(item, "lease")
    async with engineering_recovery_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        author = await session.get(ExecutionWork, (COMPANY, item.author.spec.job.task_id))
        verifier = await session.get(ExecutionWork, (COMPANY, job.task_id))
        intent = await session.get(EffectIntent, (COMPANY, job.action_id))
        dispatch = await session.get(SegmentDispatch, (COMPANY, job.action_id))
        hold = await session.get(CostHold, job.action_id)
        attempts = await session.scalar(
            select(func.count())
            .select_from(ExecutionAttempt)
            .where(ExecutionAttempt.task_id == job.task_id)
        )
        assert author is not None and author.worker_id is None
        assert (
            verifier is not None and verifier.worker_id is None and verifier.tool_attempts_used == 0
        )
        assert intent is None and attempts == 0
        assert dispatch is not None and dispatch.workflow_id
        assert (
            hold is not None
            and hold.state == "held"
            and hold.amount_usd > 0
            and hold.actual_usd is None
        )
    assert await item.runner.results.load(item.verifier_spec) is None
