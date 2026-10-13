"""Prior exact approvals cannot bypass current daily/work/ancestor overbilling limits."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.contracts.actions import ActionProposal
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionDeniedError, ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_models import CostHold, DailyBudget, WorkBudget
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control, work
from nexus.tests.integration.test_company_execution_store import (
    WORKER,
    action,
    identity,
    ready,
    receipt,
    registration,
    scope,
)
from nexus.tests.integration.test_company_execution_store import (
    execution_factory as execution_factory,
)


async def second_action(
    factory: async_sessionmaker[AsyncSession], first: ActionProposal, task_id: UUID
) -> ActionProposal:
    """Reserve while both actual spend totals still fit, before the first issued charge."""
    proposal = ActionProposal.model_validate(
        first.model_dump() | {"action_id": UUID(int=811), "task_id": task_id}
    )
    journal, now = CompanyJournal(factory), datetime.now(UTC)
    await journal.submit(proposal, scope(task_id))
    await journal.approve_registered(
        scope(task_id, OWNER),
        proposal.action_id,
        action_hash(proposal),
        now,
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        scope(task_id), proposal.action_id, now, (), identity=identity()
    )
    return proposal


async def budget_values(factory: async_sessionmaker[AsyncSession]) -> tuple[object, ...]:
    """Capture all affected held/spent/date values without keeping ORM objects across sessions."""
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        daily = (
            await session.execute(
                select(DailyBudget.day, DailyBudget.held_usd, DailyBudget.spent_usd).order_by(
                    DailyBudget.day
                )
            )
        ).all()
        tasks = (
            await session.execute(
                select(WorkBudget.task_id, WorkBudget.held_usd, WorkBudget.spent_usd).order_by(
                    WorkBudget.task_id
                )
            )
        ).all()
        holds = (
            await session.execute(
                select(
                    CostHold.action_id,
                    CostHold.day,
                    CostHold.state,
                    CostHold.amount_usd,
                    CostHold.actual_usd,
                ).order_by(CostHold.action_id)
            )
        ).all()
        return tuple(daily), tuple(tasks), tuple(holds)


async def assert_denied_without_mutation(
    factory: async_sessionmaker[AsyncSession],
    execution: ExecutionStore,
    effects: EffectStore,
    target: ExecutionLease,
    proposal: ActionProposal,
    first: ActionProposal,
    actual: Decimal,
) -> None:
    before = await execution.get(scope(proposal.task_id), identity())
    budget_before = await budget_values(factory)
    with pytest.raises(ExecutionDeniedError):
        await effects.begin(target, identity(), proposal.action_id)
    assert await execution.get(scope(proposal.task_id), identity()) == before
    assert await budget_values(factory) == budget_before
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.get(EffectIntent, (COMPANY, proposal.action_id)) is None
        assert (
            await session.scalar(
                select(ExecutionAttempt).where(
                    ExecutionAttempt.company_id == COMPANY,
                    ExecutionAttempt.task_id == proposal.task_id,
                    ExecutionAttempt.attempt_id == proposal.action_id,
                )
            )
            is None
        )
        issued = await session.get(CostHold, first.action_id)
        held = await session.get(CostHold, proposal.action_id)
        assert issued is not None and issued.actual_usd == actual and issued.state == "reconciled"
        assert held is not None and held.actual_usd is None and held.state == "held"


@pytest.mark.parametrize("boundary", ["daily", "own_work", "ancestor"])
async def test_fresh_effect_rechecks_all_current_caps_after_truthful_overbill(
    execution_factory: async_sessionmaker[AsyncSession], boundary: str
) -> None:
    execution, effects = await ready(execution_factory)
    first = await action(execution_factory)
    other = first.task_id if boundary == "own_work" else UUID(int=810)
    if other != first.task_id:
        ancestor = boundary == "ancestor"
        directory = PersistentCompanyDirectory(execution_factory)
        await directory.register_work(
            work(
                other,
                parent=first.task_id if ancestor else None,
                amount="0.40" if ancestor else "1.00",
            ),
            control(),
        )
        quota = AttemptQuota(model_requests=0, tool_attempts=1, rework_rounds=0, plan_revisions=0)
        await execution.register(
            registration(
                other, amount="0.40" if ancestor else "1.00", quota=quota if ancestor else None
            ),
            scope(other),
            identity(),
        )
    second = await second_action(execution_factory, first, other)
    initial = await execution.claim(scope(), identity(), WORKER)
    await effects.begin(initial, identity(), first.action_id)
    actual = Decimal({"daily": "4.95", "own_work": "1.10", "ancestor": "0.75"}[boundary])
    await effects.record_receipt(initial, identity(), receipt(first), actual_usd=actual)
    target = initial
    if other != first.task_id:
        await execution.release(initial, identity())
        target = await execution.claim(scope(other), identity(), UUID(int=812))
    await assert_denied_without_mutation(
        execution_factory, execution, effects, target, second, first, actual
    )
