"""Post-intent current managed admission reuses actual server configuration, never caller gates."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.execution.runtime_support import execution_row, lease_scope, runtime_transaction
from nexus.tests.generated_artifact_fixture import generated_scenario
from nexus.tests.integration.test_company_directory import ACTOR, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.receipt_event_support import receipt_factory as receipt_factory


@pytest.mark.parametrize("revoked", [False, True])
async def test_post_intent_execution_preflight_observes_actual_plan_revocation(
    receipt_factory: async_sessionmaker[AsyncSession], tmp_path: Path, revoked: bool
) -> None:
    item = await generated_scenario(receipt_factory, tmp_path, production=True)
    scope = lease_scope(item.lease)
    async with runtime_transaction(receipt_factory, scope, identity(ACTOR)) as (session, _, _):
        binding = await item.plans.current_binding(session, scope.company_id, scope.task_id)
        assert binding is not None
    if revoked:
        await item.plans.revoke(
            control(),
            identity(OWNER),
            binding.plan.plan_revision_id,
            binding.plan.sha256,
            expected_current_revision_id=binding.plan.plan_revision_id,
        )
    async with runtime_transaction(receipt_factory, scope, identity(ACTOR)) as (
        session,
        control_row,
        _,
    ):
        work = await execution_row(session, scope)
        if revoked:
            with pytest.raises(ValueError):
                await item.effects.revalidate_execution_locked(
                    session, control_row, work, identity(ACTOR), item.action, "tool_attempts"
                )
        else:
            await item.effects.revalidate_execution_locked(
                session, control_row, work, identity(ACTOR), item.action, "tool_attempts"
            )
