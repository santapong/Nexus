"""Actual current input source fixture reads and registered immutable no-expiry policy."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.evidence_models import BrainEvidence
from nexus.company.brain.ingestion_store import BrainIngestionStore
from nexus.company.brain.retrieval import CitationHandle
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.brain.source_models import BrainSourceHead
from nexus.company.brain.source_registry import SourceRegistry
from nexus.tests.integration.management_acceptance_source_fixture import Policies
from nexus.tests.integration.test_company_brain_ingestion import (
    SOURCE,
    Reader,
    command,
    owner_scope,
)
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity


async def current_input_source(
    factory: async_sessionmaker[AsyncSession],
    reader: PersistentBrainRetriever,
) -> tuple[ArtifactSlice, tuple[CitationHandle, ...]]:
    async with brain_transaction(factory, owner_scope(), identity(OWNER)) as (session, _, _):
        head = await session.get(BrainSourceHead, (COMPANY, SOURCE))
        assert head is not None
        ids = tuple(
            (
                await session.scalars(
                    select(BrainEvidence.evidence_id)
                    .where(
                        BrainEvidence.company_id == COMPANY,
                        BrainEvidence.source_revision_id == head.current_revision_id,
                    )
                    .order_by(BrainEvidence.evidence_id)
                )
            ).all()
        )
    handles = await reader.citation_handles(
        owner_scope(), identity(OWNER), ids, include_history=False
    )
    source = await reader.bounded_artifact(
        owner_scope(),
        identity(OWNER),
        handles[0].record.artifact.artifact_revision_id,
        start_byte=0,
        max_bytes=16384,
        include_history=False,
    )
    return source, handles


async def register_immutable_input(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    policies: Policies,
) -> None:
    # This changes the actual operator policy and ingests a new native revision; no SQL None seed.
    previous = policies.policy("fixture.source.v1")
    policy = previous.model_copy(update={"freshness_seconds": None})
    policies.values[policy.source_symbol] = policy
    async with brain_transaction(factory, owner_scope(), identity(OWNER)) as (session, _, _):
        head = await session.get(BrainSourceHead, (COMPANY, SOURCE))
        assert head is not None
        revision = head.current_revision_id
    raw = b"Current immutable registered source snapshot for the actual report."
    ingest = BrainIngestionStore(
        factory,
        SourceRegistry((policy,), Reader({"2": raw})),
        ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"),
    )
    await ingest.ingest(owner_scope(), identity(OWNER), command(raw, "2", revision))
