"""Retained independent artifact-source ancestry fixture; metadata edges are conformance only."""

import hashlib
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.artifact_input_models import BrainArtifactInput
from nexus.company.brain.base import SourceTime
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.ingestion_store import BrainIngestionStore
from nexus.company.brain.models import BrainEvidence
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry, SourceSnapshot
from nexus.company.brain.sources import ArtifactRevisionRef, IngestCommand, SourceRegistration
from nexus.company.management.artifact_target_store import ArtifactTargetStore
from nexus.tests.integration.test_company_artifact_input_provenance import metadata_artifact
from nexus.tests.integration.test_company_brain_ingestion import (
    Reader,
    command,
    configured,
    owner_scope,
)
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity


async def build_source_ancestor_case(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> tuple[PersistentBrainRetriever, tuple[UUID, ...], ArtifactRevisionRef]:
    public_raw = b"needle report whose artifact input inherits a private source."
    ingestion = await configured(factory, root, Reader({"r1": public_raw}))
    public = await ingestion.ingest(owner_scope(), identity(OWNER), command(public_raw, "r1"))
    private_id, private_resource = uuid4(), ResourceRef(company_id=COMPANY, resource_id=uuid4())
    hidden = b"Private original invoice source."

    class HiddenReader:
        async def read(self, registration: SourceRegistration, revision: str) -> SourceSnapshot:
            return SourceSnapshot(
                company_id=COMPANY,
                source_id=private_id,
                source_symbol="review.private.v1",
                external_key="private-invoice",
                revision=revision,
                raw_bytes=hidden,
                source_event=SourceTime(precision="unknown", value=None, basis="conformance only"),
            )

    policy = SourcePolicy(
        source_symbol="review.private.v1",
        authority_profile="review.private.v1",
        data_classification="confidential",
        media_type="text/plain",
        parser_version="utf8-identity-v1",
        chunker_version="utf8-sections-v1",
        search_config="simple",
        freshness_seconds=3600,
        allowed_external_keys=frozenset({"private-invoice"}),
    )
    blobs = ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1")
    private_store = BrainIngestionStore(factory, SourceRegistry((policy,), HiddenReader()), blobs)
    await private_store.register(
        owner_scope(),
        identity(OWNER),
        SourceRegistration(
            company_id=COMPANY,
            source_id=private_id,
            resource=private_resource,
            source_symbol=policy.source_symbol,
            external_key="private-invoice",
        ),
        readers=(OWNER,),
    )
    private_artifact = ArtifactRevisionRef(
        company_id=COMPANY,
        artifact_id=uuid4(),
        artifact_revision_id=uuid4(),
        revision="v1",
        sha256=hashlib.sha256(hidden).hexdigest(),
        byte_length=len(hidden),
    )
    private = await private_store.ingest(
        owner_scope(),
        identity(OWNER),
        IngestCommand(
            company_id=COMPANY,
            source_id=private_id,
            revision="v1",
            artifact=private_artifact,
        ),
    )
    # Both artifact resources are granted. The ancestor's source resource remains private.
    parent_resource = ResourceRef(company_id=COMPANY, resource_id=uuid4())
    await ArtifactTargetStore(factory).provision(
        owner_scope(), identity(OWNER), parent_resource, readers=(OWNER, ACTOR)
    )
    parent = await metadata_artifact(
        factory, blobs, parent_resource, private.source, b"parent derived from invoice", "internal"
    )
    async with brain_transaction(factory, owner_scope(), identity(OWNER)) as (session, _, _):
        session.add(
            BrainArtifactInput(
                company_id=COMPANY,
                artifact_revision_id=public.artifact.artifact_revision_id,
                input_artifact_revision_id=parent.artifact_revision_id,
            )
        )
        ids = tuple(
            (
                await session.scalars(
                    select(BrainEvidence.evidence_id).where(
                        BrainEvidence.company_id == COMPANY,
                        BrainEvidence.source_revision_id == public.source.source_revision_id,
                    )
                )
            ).all()
        )
    return (
        PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits(max_candidates=1)),
        ids,
        public.artifact,
    )
