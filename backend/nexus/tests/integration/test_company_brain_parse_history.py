"""Changed parser attempts append history without rebinding immutable source bytes or dates."""

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.evidence_models import BrainParseFailure, BrainParseRevision
from nexus.company.brain.ingestion_store import BrainIngestionStore
from nexus.company.brain.source_models import BrainArtifactRevision, BrainSourceRevision
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry
from nexus.tests.integration.test_company_brain_ingestion import (
    Reader,
    command,
    configured,
    owner_scope,
)
from nexus.tests.integration.test_company_brain_ingestion import ingest_factory as ingest_factory
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity


@pytest.mark.parametrize("recipe", ["unsupported-parser-v2", "r" * 128])
async def test_new_recipe_failure_keeps_original_raw_source_and_prior_success(
    ingest_factory: async_sessionmaker[AsyncSession], tmp_path: Path, recipe: str
) -> None:
    raw = b"original source bytes and source event\r\n"
    reader = Reader({"r1": raw})
    store = await configured(ingest_factory, tmp_path, reader)
    first = await store.ingest(owner_scope(), identity(OWNER), command(raw, "r1"))
    async with ingest_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        original = await session.get(
            BrainArtifactRevision, (COMPANY, first.artifact.artifact_revision_id)
        )
        assert original is not None
        original_at = original.recorded_at
        source = await session.get(BrainSourceRevision, (COMPANY, first.source.source_revision_id))
        assert source is not None
        ingested_at = source.ingested_at
    policy = SourcePolicy(
        source_symbol="fixture.source.v1",
        authority_profile="fixture.reported.v1",
        data_classification="internal",
        media_type="text/plain",
        parser_version=recipe,
        chunker_version="utf8-sections-v1",
        search_config="simple",
        freshness_seconds=3600,
        allowed_external_keys=frozenset({"document-1"}),
    )
    changed = BrainIngestionStore(
        ingest_factory,
        SourceRegistry((policy,), reader),
        ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1"),
    )
    attempted = command(raw, "r1", first.source.source_revision_id).model_copy(
        update={"parser_version": policy.parser_version}
    )
    failed = await changed.ingest(owner_scope(), identity(OWNER), attempted)
    assert failed.status == "quarantined" and failed.reason_code == "unsupported_recipe"
    assert await changed.ingest(owner_scope(), identity(OWNER), attempted) == failed
    async with ingest_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        stored = await session.get(
            BrainArtifactRevision, (COMPANY, first.artifact.artifact_revision_id)
        )
        assert stored is not None and stored.recorded_at == original_at
        assert stored.raw_text.encode() == raw
        source = await session.get(BrainSourceRevision, (COMPANY, first.source.source_revision_id))
        assert source is not None and source.ingested_at == ingested_at
        assert await session.scalar(select(func.count()).select_from(BrainSourceRevision)) == 1
        assert await session.scalar(select(func.count()).select_from(BrainParseRevision)) == 1
        assert await session.scalar(select(func.count()).select_from(BrainParseFailure)) == 1
