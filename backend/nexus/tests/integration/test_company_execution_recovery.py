"""Execution boundary negatives, using the same private DB and actual profile migrations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.contracts.results import VerificationResult
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    TASK,
    TRACE,
    control,
)
from nexus.tests.integration.test_company_execution_store import (
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


async def test_execute_lease_cannot_be_reused_as_a_reconciliation_claim(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, _ = await ready(execution_factory)
    lease = await execution.claim(scope(), identity(), WORKER)
    with pytest.raises(ExecutionDeniedError):
        await execution.claim(
            scope(), identity(), WORKER, reconcile_only=True, segment_id=lease.segment_id
        )


async def test_same_segment_replay_retains_fence_and_counters(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, _ = await ready(execution_factory)
    lease = await execution.claim(scope(), identity(), WORKER)
    await execution.reserve_attempt(lease, identity(), "model_requests", uuid4())
    assert await execution.claim(scope(), identity(), WORKER, segment_id=lease.segment_id) == lease
    assert (await execution.get(scope(), identity())).counters.model_requests == 1


async def _queued_action(
    factory: async_sessionmaker[AsyncSession],
    *,
    old: bool = False,
) -> ActionProposal:
    request = ActionProposal(
        company_id=COMPANY,
        action_id=uuid4(),
        task_id=TASK,
        trace_id=TRACE,
        actor_id=ACTOR,
        revision=1,
        tool="offline.tool",
        tool_version="v1",
        resource="fixture:source",
        parameters={"synthetic": True},
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.10"),
        preconditions=(ResourceRevision(resource="fixture:source", revision="source-v1"),),
    )
    now = datetime.now(UTC) - timedelta(hours=25) if old else datetime.now(UTC)
    journal = CompanyJournal(factory)
    await journal.submit(request, scope())
    await journal.approve_registered(
        scope(principal=OWNER),
        request.action_id,
        action_hash(request),
        now,
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        scope(), request.action_id, now, request.preconditions, identity=identity()
    )
    return request


@pytest.mark.parametrize("old", [True, False])
async def test_queued_expiry_or_changed_source_is_rechecked_at_the_effect_boundary(
    execution_factory: async_sessionmaker[AsyncSession],
    old: bool,
) -> None:
    execution, effects = await ready(execution_factory)
    request = await _queued_action(execution_factory, old=old)
    lease = await execution.claim(scope(), identity(), WORKER)
    revisions = (
        request.preconditions
        if old
        else (ResourceRevision(resource="fixture:source", revision="source-v2"),)
    )
    with pytest.raises(ExecutionDeniedError):
        await effects.begin(lease, identity(), request.action_id, resources=revisions)
    assert (await execution.get(scope(), identity())).counters.tool_attempts == 0


async def test_parent_slice_and_counters_survive_a_queued_day_change(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Lifetime runtime counters have no date key; a queue wait cannot grant a reset.
    execution, effects = await ready(execution_factory)
    request = await _queued_action(execution_factory, old=True)
    lease = await execution.claim(scope(), identity(), WORKER)
    await execution.reserve_attempt(lease, identity(), "model_requests", uuid4())
    with pytest.raises(ExecutionDeniedError):
        await effects.begin(lease, identity(), request.action_id, resources=request.preconditions)
    await expire_lease()
    resumed = await execution.claim(scope(), identity(), WORKER)
    assert resumed.run_id == lease.run_id
    assert (await execution.get(scope(), identity())).counters.model_requests == 1


async def test_cancelled_work_stops_new_calls_but_can_reconcile_an_issued_effect(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, effects = await ready(execution_factory)
    approved = await action(execution_factory)
    original = await execution.claim(scope(), identity(), WORKER)
    await effects.begin(original, identity(), approved.action_id)
    await PersistentCompanyDirectory(execution_factory).set_work_active(
        control(), task_id=TASK, active=False
    )
    await expire_lease()
    with pytest.raises(ExecutionDeniedError):
        await execution.claim(scope(), identity(), WORKER)
    current = await execution.claim(scope(), identity(), WORKER, reconcile_only=True)
    assert (await effects.reconcile(current, identity(), receipt(approved))).state == "succeeded"


async def test_queued_authority_rechecks_policy_before_committing_intent(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, effects = await ready(execution_factory)
    approved = await action(execution_factory)
    lease = await execution.claim(scope(), identity(), WORKER)
    admin = create_async_engine(settings.company_test_database_url)
    try:
        async with admin.begin() as connection:
            await connection.execute(
                text("UPDATE company_controls SET price_version='changed-prices'")
            )
    finally:
        await admin.dispose()
    with pytest.raises(ExecutionDeniedError):
        await effects.begin(lease, identity(), approved.action_id)
    assert (await execution.get(scope(), identity())).counters.tool_attempts == 0


async def test_expired_lease_cannot_reserve_or_record_even_before_reclaim(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, effects = await ready(execution_factory)
    approved = await action(execution_factory)
    lease = await execution.claim(scope(), identity(), WORKER)
    await effects.begin(lease, identity(), approved.action_id)
    await expire_lease()
    with pytest.raises(ExecutionDeniedError):
        await effects.record_receipt(lease, identity(), receipt(approved))
    with pytest.raises(ExecutionDeniedError):
        await execution.reserve_attempt(lease, identity(), "model_requests", uuid4())


async def test_stale_verification_cannot_advance_known_receipt_and_candidate_is_not_completion(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, effects = await ready(execution_factory)
    approved = await action(execution_factory)
    lease = await execution.claim(scope(), identity(), WORKER)
    await effects.begin(lease, identity(), approved.action_id)
    await effects.record_receipt(lease, identity(), receipt(approved))
    candidate = VerificationResult(
        company_id=COMPANY,
        verification_id=uuid4(),
        action_id=approved.action_id,
        verifier_id=UUID(int=90),
        verdict="pass",
        criterion_ids=("fixture-criterion",),
        evidence_ids=(UUID(int=91),),
        limitations=("Synthetic candidate; no evidence lookup performed",),
    )
    await effects.record_verification_candidate(lease, identity(), candidate)
    assert (await execution.get(scope(), identity())).state == "verifying"
    await expire_lease()
    new = await execution.claim(scope(), identity(), UUID(int=93))
    with pytest.raises(ExecutionDeniedError):
        await effects.record_verification_candidate(lease, identity(), candidate)
    assert (await effects.get(new, identity(), approved.action_id)).receipt is not None
    assert (await execution.get(scope(), identity())).counters.tool_attempts == 1


async def test_database_counter_floor_and_tenant_isolation_are_real(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, _ = await ready(execution_factory)
    lease = await execution.claim(scope(), identity(), WORKER)
    await execution.reserve_attempt(lease, identity(), "model_requests", uuid4())
    async with execution_factory() as session, session.begin():
        # No company context means a genuine non-superuser read sees no work.
        assert await session.scalar(text("SELECT count(*) FROM company_execution_work")) == 0
    with pytest.raises(DBAPIError):
        async with execution_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            await session.execute(text("UPDATE company_execution_work SET model_requests_used=0"))
    assert (await execution.get(scope(), identity())).counters.model_requests == 1


async def test_corrupt_non_owner_role_cannot_claim_or_consume_runtime_allowance(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, _ = await ready(execution_factory)
    admin = create_async_engine(settings.company_test_database_url)
    try:
        async with admin.begin() as connection:
            await connection.execute(
                text("UPDATE company_memberships SET role='owner' WHERE principal_id=:actor"),
                {"actor": ACTOR},
            )
    finally:
        await admin.dispose()
    with pytest.raises(ExecutionDeniedError):
        await execution.claim(scope(), identity(), WORKER)
    current = await execution.get(scope(principal=OWNER), identity(OWNER))
    assert current.counters.model_requests == 0 and current.worker_id is None
