"""Actual owner metric publisher conformance on its exclusive normal profile database."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.management.control_support import ManagementConflictError
from nexus.company.management.metric_models import ManagementMetricObservation
from nexus.company.management.transactions import (
    management_owner_transaction,
)
from nexus.settings import settings
from nexus.tests.generated_artifact_fixture import ledger
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control, migrate
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.metric_fixture import accept_report, configured_metric


@pytest.fixture
async def metrics_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_metrics"
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


async def test_absent_acceptance_is_native_zero_and_replay_preserves_time_and_counters(
    metrics_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await configured_metric(metrics_factory, tmp_path)
    author = case.payload.children[0].binding
    before = await case.execution.get(ledger(author), identity(author.actor_id))
    scope = control()
    record = await case.store.observe(scope, identity(OWNER), case.request)
    assert record.snapshot.comparison.value.kind == "known"
    assert record.snapshot.comparison.value.value == 0
    assert record.snapshot.comparison.baseline.kind == "unknown"
    replay = await case.store.observe(scope, identity(OWNER), case.request)
    assert replay == record and replay.observed_at == record.observed_at
    after = await case.execution.get(ledger(author), identity(author.actor_id))
    assert before.counters == after.counters and before.segment_number == after.segment_number
    assert await case.store.get_saved(control(), identity(OWNER), record.observation_id) == record
    with pytest.raises(ManagementConflictError):
        await case.store.observe(
            scope, identity(OWNER), case.request.model_copy(update={"observation_id": uuid4()})
        )


async def test_actual_native_protected_acceptance_measures_one_without_inventing_baseline(
    metrics_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await configured_metric(metrics_factory, tmp_path)
    accepted = await accept_report(metrics_factory, case)
    record = await case.store.observe(control(), identity(OWNER), case.request)
    snapshot = record.snapshot
    assert snapshot.comparison.value.kind == "known" and snapshot.comparison.value.value == 1
    assert snapshot.comparison.result == "satisfied" and snapshot.comparison.baseline_change is None
    assert snapshot.comparison.baseline.kind == "unknown"
    assert snapshot.work[0].acceptance_id == accepted.acceptance_id
    assert snapshot.work[0].receipt_id == accepted.target.receipt_id
    assert snapshot.work[0].proof_ids == tuple(row.proof_id for row in accepted.proofs)
    assert snapshot.resources and snapshot.sources
    assert all(row.head.current == row.source for row in snapshot.sources)
    current = await case.store.current(control(), identity(OWNER), record.observation_id)
    assert current is not None and current.comparison_result == "satisfied"
    assert current.recorded_at == record.observed_at and current.baseline_change is None


async def test_wrong_owner_goal_plan_or_task_cannot_publish_metric(
    metrics_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await configured_metric(metrics_factory, tmp_path)
    with pytest.raises(BrainDeniedError):
        await case.store.observe(control(), identity(ACTOR), case.request)
    for update in (
        {"goal": case.request.goal.model_copy(update={"sha256": "f" * 64})},
        {"plan": case.request.plan.model_copy(update={"sha256": "f" * 64})},
        {"task_ids": (uuid4(),)},
    ):
        with pytest.raises(ManagementConflictError):
            await case.store.observe(
                control(), identity(OWNER), case.request.model_copy(update=update)
            )
    async with management_owner_transaction(metrics_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert (
            await session.get(ManagementMetricObservation, (COMPANY, case.request.observation_id))
            is None
        )


async def test_same_observation_replay_cannot_replace_operation_or_audit_identity(
    metrics_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await configured_metric(metrics_factory, tmp_path)
    scope = control()
    original = await case.store.observe(scope, identity(OWNER), case.request)
    for changed in (
        scope.model_copy(update={"operation_id": uuid4()}),
        scope.model_copy(update={"trace_id": uuid4()}),
    ):
        with pytest.raises(ManagementConflictError):
            await case.store.observe(changed, identity(OWNER), case.request)
    assert await case.store.get_saved(scope, identity(OWNER), original.observation_id) == original


async def test_historical_protected_read_has_bounded_cancellation(
    metrics_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from nexus.company.access import CompanyControlScope, VerifiedIdentity
    from nexus.company.brain.artifact_store import BoundedArtifactReader
    from nexus.company.management import metric_read, metric_store
    from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
    from nexus.company.management.metric_contracts import MetricObservationRecord
    from nexus.harness.journal_models import CompanyControl

    case = await configured_metric(metrics_factory, tmp_path)
    record = await case.store.observe(control(), identity(OWNER), case.request)
    entered = asyncio.Event()

    async def pending(
        session: AsyncSession,
        company: CompanyControl,
        scope: CompanyControlScope,
        signed: VerifiedIdentity,
        record: MetricObservationRecord,
        artifacts: BoundedArtifactReader,
        freshness: RegisteredSourceFreshness,
    ) -> None:
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(metric_read, "require_saved_read", pending)
    monkeypatch.setattr(metric_store, "METRIC_TIMEOUT_SECONDS", 0.2)
    with pytest.raises(TimeoutError):
        await case.store.get_saved(control(), identity(OWNER), record.observation_id)
    assert entered.is_set()
