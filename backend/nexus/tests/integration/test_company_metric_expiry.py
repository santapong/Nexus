"""Real grant expiry after immutable write must roll back the metric observation."""

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
from nexus.company.management import metric_store
from nexus.company.management.control_support import db_clock
from nexus.company.management.metric_contracts import MetricObservationRecord
from nexus.company.management.metric_models import ManagementMetricObservation
from nexus.company.management.metric_persistence import write_observation
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_metrics import metrics_factory as metrics_factory
from nexus.tests.metric_fixture import accept_report, configured_metric


async def test_actual_source_grant_expiry_after_metric_flush_rolls_back_observation(
    metrics_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await configured_metric(metrics_factory, tmp_path)
    await accept_report(metrics_factory, case)
    async with management_owner_transaction(metrics_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        grant = await session.get(BrainResourceAccess, (COMPANY, RESOURCE, OWNER))
        assert grant is not None
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
    original = write_observation
    reached: list[bool] = []

    async def delayed(session: AsyncSession, record: MetricObservationRecord) -> None:
        await original(session, record)
        reached.append(True)
        # Each statement stays below the production two-second statement bound.
        await session.execute(select(func.pg_sleep(1.1)))
        await session.execute(select(func.pg_sleep(1.1)))

    monkeypatch.setattr(metric_store, "write_observation", delayed)
    with pytest.raises(ManagementDeniedError, match="expired"):
        await case.store.observe(control(), identity(OWNER), case.request)
    assert reached == [True]
    async with management_owner_transaction(metrics_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        assert (
            await session.get(ManagementMetricObservation, (COMPANY, case.request.observation_id))
            is None
        )
