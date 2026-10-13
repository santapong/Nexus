"""Exact frozen fixture adaptation into normally migrated restricted PostgreSQL, unscored."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.retrieval import RetrievalLimits, SearchRequest
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.tests.brain_api_support import brain_api_factory as brain_api_factory
from nexus.tests.brain_case_seeder import seed_case


@pytest.mark.parametrize("case_id", ["B01", "B04", "B07", "B09", "B11", "B16", "B17"])
async def test_exact_source_and_derivation_fixture_seeding(
    brain_api_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    case_id: str,
) -> None:
    blobs = ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1")
    setup, pack, _ = await seed_case(brain_api_factory, blobs, case_id)
    scope = BrainReadScope(
        company_id=setup.company_id,
        workspace_id=setup.workspace_id,
        principal_id=setup.principal_id,
        operation_id=setup.operation_id,
        trace_id=setup.trace_id,
    )
    identity = VerifiedIdentity(principal_id=setup.principal_id, workspace_id=setup.workspace_id)
    retriever = PersistentBrainRetriever(brain_api_factory, blobs, limits=RetrievalLimits())
    ids = tuple(row.evidence_id for row in pack.evidence if row.case_id == case_id)
    result = await retriever.search(
        scope,
        identity,
        SearchRequest(
            company_id=scope.company_id,
            query="source",
            explicit_evidence_ids=ids,
        ),
    )
    materials = await retriever.materialize(
        scope, identity, tuple(row.handle for row in result.handles)
    )
    assert all(row.company_id == scope.company_id for row in materials)
    assert all(row.record.evidence_id in ids for row in materials)
    for row in materials:
        raw = await blobs.read(row.record.artifact)
        assert (
            row.text.encode() == raw[row.record.raw_span.start_byte : row.record.raw_span.end_byte]
        )
