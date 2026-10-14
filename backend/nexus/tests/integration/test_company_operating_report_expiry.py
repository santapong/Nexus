"""Real clock-only expiry after the final qualifier cannot return a saved private projection."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.tests.integration.operating_report_fixture import configured_report, loaded_report
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_operating_reports import (
    reports_factory as reports_factory,
)
from nexus.tests.management_plan_support import VERIFIER


async def test_final_report_read_rechecks_input_grant_expiry_after_awaited_qualification(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def grant_before_saved_snapshot() -> None:
        async with brain_transaction(reports_factory, owner_scope(), identity(OWNER)) as (
            session,
            _,
            now,
        ):
            resource = await session.get(BrainResource, (COMPANY, RESOURCE))
            assert resource is not None
            generation = resource.acl_generation
        await ResourceAccessStore(reports_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=VERIFIER,
                active=True,
                expires_at=now + timedelta(seconds=4),
                expected_generation=generation,
            ),
        )

    scenario = await configured_report(
        reports_factory, tmp_path, before_snapshot=grant_before_saved_snapshot
    )
    original = scenario.freshness.revalidate_references
    calls = 0

    async def delayed(
        session: AsyncSession,
        scope: BrainReadScope,
        references: tuple[ArtifactRevisionRef, ...],
        now: datetime,
    ) -> None:
        nonlocal calls
        # The saved-output share gate runs first; delay only the final read's actual qualifier.
        await original(session, scope, references, now)
        calls += 1
        if calls == 2:
            # Keep the production 2 s statement timeout intact while time advances 4.5 s.
            for _ in range(3):
                await session.execute(select(func.pg_sleep(1.5)))

    monkeypatch.setattr(scenario.freshness, "revalidate_references", delayed)
    with pytest.raises(ValueError):
        await loaded_report(scenario)
    assert calls == 2
