"""Independent final-commit source-grant expiry probe on a separate restricted database."""

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import nexus.company.management.acceptance_store as publisher
from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_store import append_event
from nexus.company.brain.events import EventKind, OutboxEvent
from nexus.company.management.acceptance_models import ManagementWorkAcceptance
from nexus.tests.integration.management_acceptance_fixture import (
    acceptance_factory as acceptance_factory,
)
from nexus.tests.integration.management_acceptance_fixture import configured_acceptance
from nexus.tests.integration.management_acceptance_report_fixture import bindings
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity


async def test_input_grant_expiry_during_outbox_cannot_commit_acceptance(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await configured_acceptance(acceptance_factory, tmp_path)
    verifier = bindings(scenario.payload)[2]
    async with acceptance_factory() as session:
        now = await session.scalar(select(func.clock_timestamp()))
    assert now is not None
    generation = next(
        row.generation for row in scenario.inputs.source.contributors if row.resource_id == RESOURCE
    )
    await ResourceAccessStore(acceptance_factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=verifier.actor_id,
            active=True,
            expected_generation=generation,
            expires_at=now + timedelta(seconds=3),
        ),
    )
    original = append_event

    async def delayed(
        session: AsyncSession,
        scope: BrainReadScope,
        *,
        kind: EventKind,
        resource_id: UUID,
        deduplication_key: str,
        now: datetime,
        source_revision_id: UUID | None = None,
        resource_generation: int | None = None,
        action_id: UUID | None = None,
    ) -> OutboxEvent:
        result = await original(
            session,
            scope,
            kind=kind,
            resource_id=resource_id,
            deduplication_key=deduplication_key,
            now=now,
            source_revision_id=source_revision_id,
            resource_generation=resource_generation,
            action_id=action_id,
        )
        await session.execute(select(func.pg_sleep(3.3)))
        return result

    monkeypatch.setattr(publisher, "append_event", delayed)
    with pytest.raises(ValueError):
        await scenario.store.publish_verified_result(
            scenario.verifier_lease,
            identity(verifier.actor_id),
            action_id=scenario.action_id,
            protected_result=scenario.protected_result,
        )
    async with acceptance_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(ManagementWorkAcceptance)) == 0
