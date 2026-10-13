"""Real bounded/fenced execution transactions in the private execution-test DB only."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Connection, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.company.contracts.work import WorkItem
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import (
    AttemptQuota,
    ExecutionDeniedError,
    ExecutionLease,
    ExecutionRegistration,
)
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    TASK,
    TRACE,
    WORKSPACE,
    control,
    prepare,
    work,
)

RUN, WORKER = UUID(int=40), UUID(int=41)


def scope(task_id: UUID = TASK, principal: UUID = ACTOR) -> LedgerScope:
    return LedgerScope(company_id=COMPANY, task_id=task_id, trace_id=TRACE, principal_id=principal)


def identity(principal: UUID = ACTOR) -> VerifiedIdentity:
    return VerifiedIdentity(workspace_id=WORKSPACE, principal_id=principal)


def registration(
    task_id: UUID = TASK, *, amount: str = "1.00", quota: AttemptQuota | None = None
) -> ExecutionRegistration:
    return ExecutionRegistration(
        work=WorkItem(
            company_id=COMPANY,
            task_id=task_id,
            trace_id=TRACE,
            goal_id=UUID(int=99),
            department="builder",
            title="Offline fixture",
            acceptance=("fixture-criterion",),
            budget_usd=Decimal(amount),
        ),
        run_id=RUN if task_id == TASK else uuid4(),
        workflow_name="fixture.workflow.v1",
        workflow_version="fixture-v1",
        model_profile="routine",
        model_registry_version="catalog-v1",
        quota=quota or AttemptQuota(),
    )


def migrate(connection: Connection, direction: str) -> None:
    backend = Path(__file__).resolve().parents[3]
    config = Config(str(backend / "alembic_company.ini"))
    config.set_main_option("script_location", str(backend / "company_alembic"))
    config.attributes["connection"] = connection
    if direction == "upgrade":
        assert set(inspect(connection).get_table_names()) <= {"company_alembic_version"}
        command.upgrade(config, "head")
        connection.execute(
            text("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO nexus_company_app")
        )
    else:
        command.downgrade(config, "base")


@pytest.fixture
async def execution_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    if not settings.company_test_database_url:
        pytest.skip("explicit private execution-test database is required")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_execution"
    assert settings.company_test_database_url != settings.database_url
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    migrated = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        migrated = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if migrated:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


async def ready(
    factory: async_sessionmaker[AsyncSession], *, quota: AttemptQuota | None = None
) -> tuple[ExecutionStore, EffectStore]:
    directory = await prepare(factory)
    await directory.register_work(work(), control())
    execution = ExecutionStore(factory)
    await execution.register(registration(quota=quota), scope(), identity())
    return execution, EffectStore(factory)


async def action(
    factory: async_sessionmaker[AsyncSession], *, authorize: bool = True
) -> ActionProposal:
    proposal = ActionProposal(
        company_id=COMPANY,
        action_id=uuid4(),
        task_id=TASK,
        trace_id=TRACE,
        actor_id=ACTOR,
        revision=1,
        tool="offline.tool",
        tool_version="v1",
        resource="fixture:source",
        parameters={"operation": "synthetic"},
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.10"),
    )
    journal = CompanyJournal(factory)
    await journal.submit(proposal, scope())
    if authorize:
        now = datetime.now(UTC)
        await journal.approve_registered(
            scope(principal=OWNER),
            proposal.action_id,
            action_hash(proposal),
            now,
            identity=identity(OWNER),
        )
        await journal.authorize_registered(
            scope(), proposal.action_id, now, (), identity=identity()
        )
    return proposal


def receipt(proposal: ActionProposal, *, outcome: str = "succeeded") -> ActionReceipt:
    return ActionReceipt.model_validate(
        {
            "company_id": COMPANY,
            "receipt_id": UUID(int=70),
            "action_id": proposal.action_id,
            "task_id": TASK,
            "trace_id": TRACE,
            "proposal_hash": action_hash(proposal),
            "outcome": outcome,
            "recorded_at": datetime.now(UTC),
            "external_id": "synthetic-receipt",
        }
    )


async def expire_lease() -> None:
    """Inject lost-worker expiry in this test DB; production callers cannot supply clocks."""
    engine = create_async_engine(settings.company_test_database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE company_execution_work SET lease_until = "
                    "clock_timestamp() - interval '1 second'"
                )
            )
    finally:
        await engine.dispose()


async def test_registration_is_idempotent_and_never_mints_a_new_run(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, _ = await ready(execution_factory)
    before = await execution.get(scope(), identity())
    assert await execution.register(registration(), scope(), identity()) == before
    changed = ExecutionRegistration.model_validate(
        registration().model_dump() | {"run_id": uuid4()}
    )
    with pytest.raises(ExecutionDeniedError):
        await execution.register(changed, scope(), identity())


@pytest.mark.parametrize("field", ["workflow_version", "model_profile", "model_registry_version"])
async def test_changed_execution_binding_cannot_create_fresh_allowance(
    execution_factory: async_sessionmaker[AsyncSession],
    field: str,
) -> None:
    execution, _ = await ready(execution_factory)
    request = ExecutionRegistration.model_validate(registration().model_dump() | {field: "changed"})
    with pytest.raises(ExecutionDeniedError):
        await execution.register(request, scope(), identity())


async def test_concurrent_claims_have_one_owner_and_monotone_reclaim_fence(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, _ = await ready(execution_factory)
    contenders = await asyncio.gather(
        execution.claim(scope(), identity(), WORKER),
        execution.claim(scope(), identity(), UUID(int=42)),
        return_exceptions=True,
    )
    leases = [entry for entry in contenders if isinstance(entry, ExecutionLease)]
    assert len(leases) == 1
    old = leases[0]
    renewed = await execution.renew(old, identity())
    assert renewed.fence == old.fence and renewed.expires_at >= old.expires_at
    await expire_lease()
    new = await execution.claim(scope(), identity(), UUID(int=43))
    assert new.fence > old.fence and new.run_id == old.run_id
    with pytest.raises(ExecutionDeniedError):
        await execution.renew(old, identity())


async def test_attempts_are_persisted_replay_idempotent_and_bound_to_kind(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, _ = await ready(execution_factory)
    lease = await execution.claim(scope(), identity(), WORKER)
    attempt = uuid4()
    first = await execution.reserve_attempt(lease, identity(), "model_requests", attempt)
    assert first.counters.model_requests == 1
    replay = await ExecutionStore(execution_factory).reserve_attempt(
        lease,
        identity(),
        "model_requests",
        attempt,
    )
    assert replay.counters.model_requests == 1
    with pytest.raises(ExecutionDeniedError):
        await execution.reserve_attempt(lease, identity(), "tool_attempts", attempt)


async def test_last_attempt_race_is_atomic_and_continuation_does_not_reset(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, _ = await ready(execution_factory, quota=AttemptQuota(model_requests=1))
    lease = await execution.claim(scope(), identity(), WORKER)
    outcomes = await asyncio.gather(
        execution.reserve_attempt(lease, identity(), "model_requests", uuid4()),
        execution.reserve_attempt(lease, identity(), "model_requests", uuid4()),
        return_exceptions=True,
    )
    assert sum(not isinstance(entry, Exception) for entry in outcomes) == 1
    await expire_lease()
    next_lease = await execution.claim(scope(), identity(), WORKER)
    assert next_lease.segment_id != lease.segment_id
    with pytest.raises(ExecutionDeniedError):
        await execution.reserve_attempt(next_lease, identity(), "model_requests", uuid4())
    assert (await execution.get(scope(), identity())).counters.model_requests == 1


async def test_child_quota_is_a_permanent_parent_slice_after_consumption(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, _ = await ready(execution_factory, quota=AttemptQuota(model_requests=2))
    lease = await execution.claim(scope(), identity(), WORKER)
    await execution.reserve_attempt(lease, identity(), "model_requests", uuid4())
    from nexus.company.directory_store import PersistentCompanyDirectory

    directory = PersistentCompanyDirectory(execution_factory)
    child, other = UUID(int=51), UUID(int=52)
    await directory.register_work(work(child, parent=TASK, amount="0.25"), control())
    quota = AttemptQuota(model_requests=1, tool_attempts=0, rework_rounds=0, plan_revisions=0)
    child_registration = registration(child, amount="0.25", quota=quota)
    await execution.register(child_registration, scope(child), identity())
    assert (await execution.get(scope(), identity())).delegated.model_requests == 1
    await directory.register_work(work(other, parent=TASK, amount="0.25"), control())
    with pytest.raises(ExecutionDeniedError):
        await execution.register(
            registration(other, amount="0.25", quota=quota), scope(other), identity()
        )
    with pytest.raises(ExecutionDeniedError):
        await execution.reserve_attempt(lease, identity(), "model_requests", uuid4())
    child_lease = await execution.claim(scope(child), identity(), UUID(int=53))
    await execution.reserve_attempt(child_lease, identity(), "model_requests", uuid4())
    assert (await execution.get(scope(), identity())).counters.model_requests == 1


async def test_pending_approval_releases_lease_and_continuation_retains_counters(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, _ = await ready(execution_factory)
    pending = await action(execution_factory, authorize=False)
    lease = await execution.claim(scope(), identity(), WORKER)
    await execution.reserve_attempt(lease, identity(), "model_requests", uuid4())
    waiting = await execution.await_approval(lease, identity(), pending.action_id)
    assert waiting.state == "awaiting_approval" and waiting.worker_id is None
    with pytest.raises(ExecutionDeniedError):
        await execution.reserve_attempt(lease, identity(), "tool_attempts", uuid4())
    with pytest.raises(ExecutionDeniedError):
        await execution.claim(scope(), identity(), WORKER)
    journal = CompanyJournal(execution_factory)
    now = datetime.now(UTC)
    await journal.approve_registered(
        scope(principal=OWNER),
        pending.action_id,
        action_hash(pending),
        now,
        identity=identity(OWNER),
    )
    await journal.authorize_registered(scope(), pending.action_id, now, (), identity=identity())
    resumed = await execution.claim(scope(), identity(), WORKER)
    assert resumed.run_id == lease.run_id and resumed.segment_id != lease.segment_id
    assert (await execution.get(scope(), identity())).counters.model_requests == 1


async def test_intent_is_committed_before_one_time_external_permit(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, effects = await ready(execution_factory)
    approved = await action(execution_factory)
    lease = await execution.claim(scope(), identity(), WORKER)
    started = await effects.begin(lease, identity(), approved.action_id)
    assert started.permit_external_call is True and started.record.state == "intent"
    another = EffectStore(execution_factory)
    assert (await another.get(lease, identity(), approved.action_id)).state == "intent"
    duplicate = await another.begin(lease, identity(), approved.action_id)
    assert duplicate.permit_external_call is False
    assert (await execution.get(scope(), identity())).counters.tool_attempts == 1


async def test_receipts_are_exact_idempotent_and_conflicts_cannot_overwrite(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, effects = await ready(execution_factory)
    approved = await action(execution_factory)
    lease = await execution.claim(scope(), identity(), WORKER)
    await effects.begin(lease, identity(), approved.action_id)
    recorded = receipt(approved)
    first = await effects.record_receipt(lease, identity(), recorded)
    assert first.state == "succeeded"
    assert await effects.record_receipt(lease, identity(), recorded) == first
    assert (
        await effects.begin(lease, identity(), approved.action_id)
    ).permit_external_call is False
    with pytest.raises(ExecutionDeniedError):
        await effects.record_receipt(lease, identity(), receipt(approved, outcome="failed"))


async def test_expired_intent_is_unknown_and_old_worker_cannot_record_or_reconcile(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, effects = await ready(execution_factory)
    approved = await action(execution_factory)
    old = await execution.claim(scope(), identity(), WORKER)
    await effects.begin(old, identity(), approved.action_id)
    await expire_lease()
    current = await execution.claim(scope(), identity(), UUID(int=60), reconcile_only=True)
    assert (await effects.get(current, identity(), approved.action_id)).state == "outcome_unknown"
    for method in (effects.record_receipt, effects.reconcile):
        with pytest.raises(ExecutionDeniedError):
            await method(old, identity(), receipt(approved))
    with pytest.raises(ExecutionDeniedError):
        await effects.begin(current, identity(), approved.action_id)
    resolved = await effects.reconcile(current, identity(), receipt(approved))
    assert resolved.state == "succeeded"
    assert (await execution.get(scope(), identity())).state == "verifying"


async def test_pause_blocks_new_calls_but_reconciliation_of_issued_effect_remains_possible(
    execution_factory: async_sessionmaker[AsyncSession],
) -> None:
    execution, effects = await ready(execution_factory)
    approved = await action(execution_factory)
    old = await execution.claim(scope(), identity(), WORKER)
    await effects.begin(old, identity(), approved.action_id)
    await CompanyJournal(execution_factory).set_paused(scope(principal=OWNER), True)
    await expire_lease()
    with pytest.raises(ExecutionDeniedError):
        await execution.claim(scope(), identity(), WORKER)
    current = await execution.claim(scope(), identity(), WORKER, reconcile_only=True)
    assert (await effects.reconcile(current, identity(), receipt(approved))).state == "succeeded"
    with pytest.raises(ExecutionDeniedError):
        await execution.reserve_attempt(current, identity(), "model_requests", uuid4())
