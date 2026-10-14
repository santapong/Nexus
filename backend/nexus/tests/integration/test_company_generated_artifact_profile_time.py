"""Registered profile qualification remains current after awaited native publication writes."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_store import append_event
from nexus.company.brain.events import EventKind, OutboxEvent
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.management.generated_artifact_identity import generated_reference
from nexus.tests.generated_artifact_fixture import generated_scenario
from nexus.tests.generated_artifact_support import generated_factory as generated_factory
from nexus.tests.integration.test_company_directory import COMPANY
from nexus.tests.integration.test_company_execution_store import identity


@pytest.mark.parametrize("qualification", ["health", "evaluation"])
async def test_profile_qualification_crossing_final_event_denies_metadata(
    generated_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qualification: str,
) -> None:
    scenario = await generated_scenario(generated_factory, tmp_path)
    expires = datetime.now(UTC) + timedelta(seconds=5)
    catalog = scenario.publisher.catalog
    models = tuple(
        row.model_copy(update={"health": row.health.model_copy(update={"expires_at": expires})})
        if qualification == "health"
        else row.model_copy(
            update={
                "evaluations": tuple(
                    e.model_copy(update={"expires_at": expires}) for e in row.evaluations
                )
            }
        )
        for row in catalog.models.models
    )
    scenario.publisher.catalog = catalog.model_copy(
        update={"models": catalog.models.model_copy(update={"models": models})}
    )
    import nexus.company.management.generated_artifact_rows as rows

    async def late_event(
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
        event = await append_event(
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
        await asyncio.sleep(max(0, (expires - datetime.now(UTC)).total_seconds()) + 0.1)
        return event

    monkeypatch.setattr(rows, "append_event", late_event)
    with pytest.raises(ValueError, match="registered model evidence"):
        await scenario.publisher.publish(
            scenario.lease,
            identity(scenario.lease.actor_id),
            scenario.action.action_id,
            scenario.prepared,
        )
    reference = generated_reference(scenario.prepared, scenario.action.action_id)
    assert await scenario.blobs.read(reference) == scenario.prepared.raw_bytes
    async with generated_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert (
            await session.get(BrainArtifactRevision, (COMPANY, reference.artifact_revision_id))
            is None
        )
