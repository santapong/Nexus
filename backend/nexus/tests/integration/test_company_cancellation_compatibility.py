"""Normal pre011 unmanaged M1 execution/read/reconciliation compatibility on our assigned DB."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.cancellation_support import cancellation_for_work
from nexus.tests.integration.test_company_directory import COMPANY, TASK
from nexus.tests.integration.test_company_execution_store import (
    WORKER,
    action,
    identity,
    ready,
    receipt,
    scope,
)
from nexus.tests.management_cancellation_support import (
    old_cancellation_factory as old_cancellation_factory,
)


@pytest.mark.parametrize("old_cancellation_factory", ["company_007", "company_010"], indirect=True)
async def test_pre011_actual_unmanaged_work_retains_fresh_execution_and_known_recovery(
    old_cancellation_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, effects = await ready(old_cancellation_factory)
    proposal = await action(old_cancellation_factory)
    async with old_cancellation_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await cancellation_for_work(session, COMPANY, TASK) is None
    original = await execution.claim(scope(), identity(), WORKER)
    assert (await effects.begin(original, identity(), proposal.action_id)).permit_external_call
    await execution.release(original, identity())
    current = await execution.claim(scope(), identity(), WORKER, reconcile_only=True)
    assert (
        await effects.reconcile(current, identity(), receipt(proposal), actual_usd=None)
    ).state == "succeeded"
    assert (await execution.get(scope(), identity())).counters.tool_attempts == 1
