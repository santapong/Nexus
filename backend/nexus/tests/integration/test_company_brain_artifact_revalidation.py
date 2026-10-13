"""Actual same-session artifact gate is current, permission-bound and content-exact."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.models import BrainSourceHead
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import brain_transaction
from nexus.tests.integration.test_company_brain_retrieval import factory as factory
from nexus.tests.integration.test_company_brain_retrieval import identity, ingest, scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER


@pytest.mark.parametrize("gate", ["slice", "reference"])
@pytest.mark.parametrize("change", ["none", "text", "grant"])
async def test_public_current_artifact_recheck_denies_tampered_or_revoked_snapshot(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, change: str, gate: str
) -> None:
    blobs = ProtectedBlobStore(tmp_path, storage_symbol="fixture.artifact-revalidation")
    _, _, command = await ingest(factory, blobs, "Current protected verifier result")
    reader = PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits())
    prepared = await reader.bounded_artifact(
        scope(),
        identity(),
        command.artifact.artifact_revision_id,
        start_byte=0,
        max_bytes=16384,
        include_history=False,
    )
    if change == "text":
        prepared = prepared.model_copy(update={"text": "Caller changed the protected result"})
    reference = prepared.artifact.model_copy(
        update={"sha256": "b" * 64} if change == "text" else {}
    )
    if change == "grant":
        await ResourceAccessStore(factory).change(
            scope(OWNER),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=UUID(int=101)),
                principal_id=ACTOR,
                active=False,
                expected_generation=1,
            ),
        )
    async with brain_transaction(factory, scope(), identity()) as (session, control, now):

        async def recheck() -> None:
            if gate == "reference":
                await BoundedArtifactReader(factory, blobs).revalidate_artifact_reference(
                    session, control, scope(), identity(), reference, now
                )
            else:
                await reader.revalidate_artifact(
                    session, control, scope(), identity(), prepared, now
                )

        if change == "none":
            await recheck()
        else:
            with pytest.raises(ValueError):
                await recheck()


async def test_source_freshness_expiring_after_preparation_denies_artifact_publication(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    blobs = ProtectedBlobStore(tmp_path, storage_symbol="fixture.expiring-artifact")
    _, _, command = await ingest(factory, blobs, "Source freshness does not stop at the mutex")
    async with brain_transaction(factory, scope(OWNER), identity(OWNER)) as (session, _, now):
        head = await session.get(BrainSourceHead, (COMPANY, command.source_id))
        assert head is not None
        head.fresh_until = now + timedelta(seconds=1)
    reader = PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits())
    prepared = await reader.bounded_artifact(
        scope(),
        identity(),
        command.artifact.artifact_revision_id,
        start_byte=0,
        max_bytes=16384,
        include_history=False,
    )
    async with brain_transaction(factory, scope(), identity()) as (session, control, now):
        await session.execute(select(func.pg_sleep(1.1)))
        with pytest.raises(ValueError, match="stale"):
            await reader.revalidate_artifact(session, control, scope(), identity(), prepared, now)
