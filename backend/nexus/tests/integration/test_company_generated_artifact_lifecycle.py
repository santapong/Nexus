"""Pending/known generated outputs retain truth while current authority stops publication."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import BrainBlobStore
from nexus.company.brain.event_store import append_event
from nexus.company.brain.events import EventKind, OutboxEvent
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.generated_artifact_identity import generated_reference
from nexus.tests.generated_artifact_fixture import generated_scenario
from nexus.tests.generated_artifact_support import generated_factory as generated_factory
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity


class AfterBlob:
    """Explicit test-only fault/owner-operation after bytes, outside any company transaction."""

    def __init__(self, blobs: BrainBlobStore, after: Callable[[], Awaitable[None]]) -> None:
        self.blobs, self.after = blobs, after

    @property
    def storage_symbol(self) -> str:
        return self.blobs.storage_symbol

    async def save(self, artifact: ArtifactRevisionRef, raw: bytes) -> None:
        await self.blobs.save(artifact, raw)
        await self.after()

    async def read(self, artifact: ArtifactRevisionRef) -> bytes:
        return await self.blobs.read(artifact)


async def revoke_source(factory: async_sessionmaker[AsyncSession], actor: UUID) -> None:
    from nexus.company.brain.access_contracts import ResourceRef

    await ResourceAccessStore(factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=actor,
            active=False,
            expected_generation=2,
        ),
    )


async def test_source_revoked_after_blob_preparation_leaves_pending_bytes_and_no_metadata(
    generated_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    scenario = await generated_scenario(generated_factory, tmp_path)

    async def revoke() -> None:
        await revoke_source(generated_factory, scenario.lease.actor_id)

    scenario.publisher.blobs = AfterBlob(scenario.blobs, revoke)
    with pytest.raises(ValueError):
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


async def test_known_generated_output_survives_revocation_but_current_replay_denies(
    generated_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    scenario = await generated_scenario(generated_factory, tmp_path)
    reference = await scenario.publisher.publish(
        scenario.lease,
        identity(scenario.lease.actor_id),
        scenario.action.action_id,
        scenario.prepared,
    )
    await revoke_source(generated_factory, scenario.lease.actor_id)
    with pytest.raises(ValueError):
        await scenario.publisher.publish(
            scenario.lease,
            identity(scenario.lease.actor_id),
            scenario.action.action_id,
            scenario.prepared,
        )
    async with generated_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        saved = await session.get(BrainArtifactRevision, (COMPANY, reference.artifact_revision_id))
        assert saved is not None and saved.sha256 == reference.sha256


async def test_native_lease_expiry_after_blob_preparation_denies_metadata(
    generated_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    scenario = await generated_scenario(generated_factory, tmp_path, ttl_seconds=5)

    async def expire() -> None:
        # Real lease/DB clock, with no expiry-field rewrite or caller clock override.
        await asyncio.sleep(5.1)

    scenario.publisher.blobs = AfterBlob(scenario.blobs, expire)
    with pytest.raises(ValueError):
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


async def test_actual_source_grant_expiring_during_final_event_rolls_back_metadata_and_edges(
    generated_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = await generated_scenario(generated_factory, tmp_path, source_grant_seconds=20)
    from datetime import UTC

    import nexus.company.management.generated_artifact_rows as rows
    from nexus.company.brain.access_models import BrainResourceAccess

    original = append_event
    async with generated_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        grant = await session.get(BrainResourceAccess, (COMPANY, RESOURCE, scenario.lease.actor_id))
        assert grant is not None and grant.expires_at is not None
        expires = grant.expires_at

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
        await asyncio.sleep(max(0, (expires - datetime.now(UTC)).total_seconds()) + 0.1)
        return result

    monkeypatch.setattr(rows, "append_event", late_event)
    with pytest.raises(ValueError, match="expired"):
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
        from nexus.company.brain.artifact_input_models import (
            BrainArtifactInput,
            BrainArtifactResourceInput,
        )
        from nexus.company.brain.event_models import BrainEvent

        assert await session.scalar(select(func.count()).select_from(BrainArtifactInput)) == 0
        assert (
            await session.scalar(select(func.count()).select_from(BrainArtifactResourceInput)) == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BrainEvent)
                .where(BrainEvent.action_id == scenario.action.action_id)
            )
            == 0
        )
