"""Actual scoped current discovery cannot borrow a cursor or expose stale saved count."""

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.management import metric_queries
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.control_support import db_clock
from nexus.company.management.metric_capture import CapturedMetric, capture_metric
from nexus.company.management.metric_contracts import MetricObservationRequest
from nexus.company.management.metric_queries import MetricQueries
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_metrics import metrics_factory as metrics_factory
from nexus.tests.metric_fixture import accept_report, configured_metric


async def test_current_page_has_native_time_order_and_scoped_uuid_cursor(
    metrics_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await configured_metric(metrics_factory, tmp_path)
    old = await case.store.observe(control(), identity(OWNER), case.request)
    request = case.request.model_copy(update={"observation_id": uuid4()})
    new = await case.store.observe(
        control().model_copy(update={"operation_id": uuid4()}), identity(OWNER), request
    )
    queries = MetricQueries(
        metrics_factory, case.store.catalog, case.store.artifacts, case.store.freshness
    )
    first = await queries.current_page(control(), identity(OWNER), request.goal.goal_id, limit=1)
    assert tuple(item.observation_id for item in first.observations) == (new.observation_id,)
    assert first.next_after_id == new.observation_id
    second = await queries.current_page(
        control(), identity(OWNER), request.goal.goal_id, after_id=first.next_after_id, limit=1
    )
    assert tuple(item.observation_id for item in second.observations) == (old.observation_id,)
    assert second.next_after_id is None
    with pytest.raises(ManagementDeniedError):
        await queries.current_page(control(), identity(OWNER), uuid4(), after_id=new.observation_id)
    with pytest.raises(ManagementDeniedError):
        await queries.current_page(
            control(), identity(OWNER), request.goal.goal_id, after_id=uuid4()
        )


async def test_final_page_clock_masks_first_known_count_after_later_read_crosses_grant_expiry(
    metrics_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await configured_metric(metrics_factory, tmp_path)
    await accept_report(metrics_factory, case)
    old = await case.store.observe(control(), identity(OWNER), case.request)
    request = case.request.model_copy(update={"observation_id": uuid4()})
    new = await case.store.observe(
        control().model_copy(update={"operation_id": uuid4()}), identity(OWNER), request
    )
    async with management_owner_transaction(metrics_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        resource = await session.get(BrainResource, (COMPANY, RESOURCE))
        assert resource is not None
        generation, now = resource.acl_generation, await db_clock(session)
    await ResourceAccessStore(metrics_factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=OWNER,
            active=True,
            expected_generation=generation,
            expires_at=now + timedelta(seconds=2),
        ),
    )
    original = capture_metric
    captured_known: list[bool] = []

    async def delayed(
        session: AsyncSession,
        company: CompanyControl,
        scope: CompanyControlScope,
        signed: VerifiedIdentity,
        selected: MetricObservationRequest,
        catalog: PlanAdmissionCatalog,
        reader: BoundedArtifactReader,
        freshness: RegisteredSourceFreshness,
    ) -> CapturedMetric:
        captured = await original(
            session, company, scope, signed, selected, catalog, reader, freshness
        )
        captured_known.append(captured.snapshot.comparison.value.kind == "known")
        if len(captured_known) == 2:
            await session.execute(select(func.pg_sleep(1.1)))
            await session.execute(select(func.pg_sleep(1.1)))
        return captured

    monkeypatch.setattr(metric_queries, "capture_metric", delayed)
    queries = MetricQueries(
        metrics_factory, case.store.catalog, case.store.artifacts, case.store.freshness
    )
    page = await queries.current_page(control(), identity(OWNER), request.goal.goal_id, limit=2)
    assert captured_known == [True, True]
    assert {row.observation_id for row in page.observations} == {
        old.observation_id,
        new.observation_id,
    }
    assert all(row.snapshot.comparison.value.kind == "unknown" for row in page.observations)
    assert all(
        not row.snapshot.sources and not row.snapshot.work[0].artifacts for row in page.observations
    )
