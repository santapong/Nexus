"""Same-session directory/runtime batch registration conserves actual parent allowances."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_contracts import DirectoryDeniedError, WorkRegistration
from nexus.company.directory_models import RegisteredWork
from nexus.execution.runtime_contracts import (
    AttemptQuota,
    ExecutionDeniedError,
    ExecutionRegistration,
)
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_registration import register_locked
from nexus.tests.integration.test_company_directory import (
    COMPANY,
    OWNER,
    TASK,
    TRACE,
    WORKSPACE,
    control,
    prepare,
    work,
)
from nexus.tests.integration.test_company_directory import directory_factory as directory_factory


def execution(request: WorkRegistration, quota: int) -> ExecutionRegistration:
    return ExecutionRegistration(
        work=WorkItem(
            company_id=request.company_id,
            task_id=request.task_id,
            trace_id=request.trace_id,
            goal_id=UUID(int=100),
            department="research",
            title="Bounded internal research",
            acceptance=("current exact citations",),
            budget_usd=request.allocation_usd,
        ),
        run_id=UUID(int=request.task_id.int + 100),
        workflow_name="management.internal-report.v1",
        workflow_version="fixture.v1",
        model_profile="fixture.model.v1",
        model_registry_version="fixture.registry.v1",
        quota=AttemptQuota(
            model_requests=quota, tool_attempts=0, rework_rounds=0, plan_revisions=0
        ),
    )


async def bind_runtime(session: AsyncSession, request: WorkRegistration, quota: int) -> None:
    row = await session.get(RegisteredWork, (COMPANY, request.task_id))
    assert row is not None
    await register_locked(session, execution(request, quota), row)


# Keep this >50-line actual transaction proof together so both USD and runtime
# quota rollback/idempotent-replay assertions remain auditable in one scenario.
@pytest.mark.parametrize("reject", [False, True])
async def test_atomic_children_commit_all_or_preserve_entire_parent_allowance(
    directory_factory: async_sessionmaker[AsyncSession], reject: bool
) -> None:
    directory = await prepare(directory_factory)
    await directory.register_work(work(), control())
    async with directory_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        await bind_runtime(session, work(), 12)
    signed = VerifiedIdentity(principal_id=OWNER, workspace_id=WORKSPACE)
    children = (
        work(UUID(int=11), parent=TASK, amount="0.40"),
        work(UUID(int=12), parent=TASK, amount="0.40"),
    )

    async def register_batch() -> None:
        async with directory_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            for child in children:
                await directory.register_work_in_transaction(session, child, control(), signed)
                await bind_runtime(session, child, 7 if reject else 6)
            # Exact replay within the same transaction cannot delegate twice.
            await directory.register_work_in_transaction(session, children[0], control(), signed)
            await bind_runtime(session, children[0], 7 if reject else 6)

    if reject:
        with pytest.raises(ExecutionDeniedError):
            await register_batch()
    else:
        await register_batch()
    allocation = await directory.allocation(COMPANY, TASK, trace_id=TRACE)
    assert allocation is not None
    assert allocation.delegated_usd == (Decimal(0) if reject else Decimal("0.80"))
    async with directory_factory() as session:
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        parent = await session.get(ExecutionWork, (COMPANY, TASK))
        assert parent is not None and parent.model_requests_limit == 12
        assert parent.model_requests_delegated == (0 if reject else 12)
        assert parent.model_requests_used == 0
        for child in children:
            registered = await session.get(RegisteredWork, (COMPANY, child.task_id))
            initialized = await session.get(ExecutionWork, (COMPANY, child.task_id))
            assert (
                (registered is None and initialized is None)
                if reject
                else (registered is not None and initialized is not None)
            )


async def test_caller_transaction_still_requires_bound_verified_owner(
    directory_factory: async_sessionmaker[AsyncSession],
) -> None:
    directory = await prepare(directory_factory)
    wrong = VerifiedIdentity(principal_id=OWNER, workspace_id=UUID(int=999))
    async with directory_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        with pytest.raises(DirectoryDeniedError):
            await directory.register_work_in_transaction(session, work(), control(), wrong)
        assert await session.get(RegisteredWork, (COMPANY, TASK)) is None
