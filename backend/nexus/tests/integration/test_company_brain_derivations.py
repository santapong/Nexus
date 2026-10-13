"""Source-derived outputs retain contributors and cannot broaden private input readership."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.base import SourceTime
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.claims import DerivationRecord
from nexus.company.brain.derivation_models import BrainDerivationSource
from nexus.company.brain.ingestion_store import BrainIngestionStore
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.source_models import BrainSourceRevision
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry, SourceSnapshot
from nexus.company.brain.sources import (
    ArtifactRevisionRef,
    EvidenceRef,
    IngestCommand,
    SourceRegistration,
)
from nexus.tests.integration.test_company_brain_ingestion import (
    RESOURCE,
    SOURCE,
    Reader,
    command,
    configured,
    owner_scope,
)
from nexus.tests.integration.test_company_brain_ingestion import ingest_factory as ingest_factory
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity


@pytest.mark.parametrize(
    "problem", ["none", "revoked_recipient", "classification", "missing_evidence"]
)
async def test_derivative_keeps_exact_source_chain_and_denies_revoked_recipient(
    ingest_factory: async_sessionmaker[AsyncSession], tmp_path: Path, problem: str
) -> None:
    source = await configured(
        ingest_factory, tmp_path, Reader({"r1": b"original protected content"})
    )
    original = await source.ingest(
        owner_scope(), identity(OWNER), command(b"original protected content", "r1")
    )
    raw = b"deterministic summary of the protected source"
    artifact = ArtifactRevisionRef(
        company_id=COMPANY,
        artifact_id=UUID(int=2001),
        artifact_revision_id=UUID(int=2002),
        revision="s1",
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
    )
    derivation = DerivationRecord(
        company_id=COMPANY,
        derivation_id=UUID(int=2003),
        artifact=artifact,
        recipe_version="fixture.summary.v1",
        kind="summary",
        contributors=(original.source,),
        evidence=(EvidenceRef(company_id=COMPANY, evidence_id=UUID(int=2999)),)
        if problem == "missing_evidence"
        else (),
        recorded_at=datetime.now(UTC),
    )

    class SummaryReader:
        async def read(self, registration: SourceRegistration, revision: str) -> SourceSnapshot:
            return SourceSnapshot(
                company_id=COMPANY,
                source_id=UUID(int=2000),
                source_symbol="fixture.summary.v1",
                external_key="summary-1",
                revision=revision,
                raw_bytes=raw,
                source_event=SourceTime(precision="unknown", value=None, basis="fixture summary"),
                derivation=derivation,
            )

    policy = SourcePolicy(
        source_symbol="fixture.summary.v1",
        authority_profile="fixture.derived.v1",
        data_classification="public" if problem == "classification" else "internal",
        origin_kind="derived",
        media_type="text/plain",
        parser_version="utf8-identity-v1",
        chunker_version="utf8-sections-v1",
        search_config="simple",
        freshness_seconds=None,
        allowed_external_keys=frozenset({"summary-1"}),
    )
    store = BrainIngestionStore(
        ingest_factory,
        SourceRegistry((policy,), SummaryReader()),
        ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1"),
    )
    await store.register(
        owner_scope(),
        identity(OWNER),
        SourceRegistration(
            company_id=COMPANY,
            source_id=UUID(int=2000),
            resource=ResourceRef(company_id=COMPANY, resource_id=UUID(int=2004)),
            source_symbol="fixture.summary.v1",
            external_key="summary-1",
        ),
        readers=(OWNER, ACTOR),
    )
    if problem == "revoked_recipient":
        await ResourceAccessStore(ingest_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=ACTOR,
                active=False,
                expected_generation=1,
            ),
        )
    if problem != "none":
        with pytest.raises(BrainDeniedError):
            await store.ingest(
                owner_scope(),
                identity(OWNER),
                IngestCommand(
                    company_id=COMPANY, source_id=UUID(int=2000), revision="s1", artifact=artifact
                ),
            )
    else:
        accepted = await store.ingest(
            owner_scope(),
            identity(OWNER),
            IngestCommand(
                company_id=COMPANY, source_id=UUID(int=2000), revision="s1", artifact=artifact
            ),
        )
        assert accepted.status == "accepted" and accepted.source.source_id != SOURCE
        async with ingest_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            linked = await session.get(
                BrainSourceRevision, (COMPANY, accepted.source.source_revision_id)
            )
            assert linked is not None and linked.derivation_id == derivation.derivation_id
            edge = await session.scalar(select(BrainDerivationSource))
            assert (
                edge is not None and edge.source_revision_id == original.source.source_revision_id
            )
