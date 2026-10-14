"""Restricted-PG artifact lineage conformance; seeded metadata is not operative work approval."""

import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.artifact_input_models import BrainArtifactInput, BrainArtifactResourceInput
from nexus.company.brain.artifact_input_support import artifact_input_closure
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.claims import DerivationRecord
from nexus.company.brain.derivation_support import save_derivation
from nexus.company.brain.models import BrainArtifactRevision
from nexus.company.brain.retrieval import RetrievalLimits, SearchRequest
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry
from nexus.company.brain.sources import ArtifactRevisionRef, SourceRevisionRef
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.artifact_target_store import ArtifactTargetStore
from nexus.settings import settings
from nexus.tests.integration.test_company_brain_access import scope
from nexus.tests.integration.test_company_brain_ingestion import (
    Reader,
    command,
    configured,
    owner_scope,
)
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, migrate
from nexus.tests.integration.test_company_execution_store import identity


@pytest.fixture
async def provenance_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_artifacts"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


@dataclass(frozen=True)
class LineageScenario:
    reader: BoundedArtifactReader
    search: PersistentBrainRetriever
    freshness: RegisteredSourceFreshness
    parent: ArtifactRevisionRef
    output: ArtifactRevisionRef
    private: ResourceRef
    source_artifact: ArtifactRevisionRef


async def metadata_scenario(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> LineageScenario:
    source_raw = b"Source ledger context needle available only through complete permission."
    ingestion = await configured(factory, root, Reader({"r1": source_raw}))
    received = await ingestion.ingest(owner_scope(), identity(OWNER), command(source_raw, "r1"))
    private = ResourceRef(company_id=COMPANY, resource_id=uuid4())
    output_resource = ResourceRef(company_id=COMPANY, resource_id=uuid4())
    targets = ArtifactTargetStore(factory)
    await targets.provision(owner_scope(), identity(OWNER), private, readers=(OWNER,))
    await targets.provision(owner_scope(), identity(OWNER), output_resource, readers=(OWNER, ACTOR))
    blobs = ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1")
    parent = await metadata_artifact(
        factory, blobs, private, received.source, b'{"private":"invoice"}', "confidential"
    )
    output = await metadata_artifact(
        factory, blobs, output_resource, received.source, b'{"report":"derived"}', "internal"
    )
    async with brain_transaction(factory, owner_scope(), identity(OWNER)) as (session, _, _):
        session.add(
            BrainArtifactInput(
                company_id=COMPANY,
                artifact_revision_id=output.artifact_revision_id,
                input_artifact_revision_id=parent.artifact_revision_id,
            )
        )
    policy = SourcePolicy(
        source_symbol="fixture.source.v1",
        authority_profile="fixture.reported.v1",
        data_classification="internal",
        media_type="text/plain",
        parser_version="utf8-identity-v1",
        chunker_version="utf8-sections-v1",
        search_config="simple",
        freshness_seconds=3600,
        allowed_external_keys=frozenset({"document-1"}),
    )
    return LineageScenario(
        BoundedArtifactReader(factory, blobs),
        PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits()),
        RegisteredSourceFreshness(factory, SourceRegistry((policy,), Reader({}))),
        parent,
        output,
        private,
        received.artifact,
    )


async def metadata_artifact(
    factory: async_sessionmaker[AsyncSession],
    blobs: ProtectedBlobStore,
    resource: ResourceRef,
    source: SourceRevisionRef,
    raw: bytes,
    classification: str,
) -> ArtifactRevisionRef:
    reference = ArtifactRevisionRef(
        company_id=COMPANY,
        artifact_id=uuid4(),
        artifact_revision_id=uuid4(),
        revision="fixture-v1",
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
    )
    await blobs.save(reference, raw)
    async with brain_transaction(factory, owner_scope(), identity(OWNER)) as (session, _, now):
        derivation_id = uuid4()
        session.add(
            BrainArtifactRevision(
                **reference.model_dump(exclude={"schema_version"}),
                resource_id=resource.resource_id,
                media_type="application/json",
                storage_symbol=blobs.storage_symbol,
                raw_text=raw.decode(),
                recorded_at=now,
                derivation_id=derivation_id,
                data_classification=classification,
            )
        )
        await session.flush()
        await save_derivation(
            session,
            DerivationRecord(
                company_id=COMPANY,
                derivation_id=derivation_id,
                artifact=reference,
                recipe_version="conformance-only",
                kind="summary",
                contributors=(source,),
                recorded_at=now,
            ),
        )
    return reference


async def test_private_input_blocks_read_and_qualification_then_grant_preserves_classification(
    provenance_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await metadata_scenario(provenance_factory, tmp_path)
    with pytest.raises(ValueError):
        await case.reader.bounded_artifact(
            scope(),
            identity(ACTOR),
            case.output.artifact_revision_id,
            start_byte=0,
            max_bytes=16384,
            include_history=False,
        )
    async with brain_transaction(provenance_factory, scope(), identity(ACTOR)) as (session, _, now):
        with pytest.raises(ValueError):
            await case.freshness.revalidate_references(session, scope(), (case.output,), now)
    await ResourceAccessStore(provenance_factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=case.private,
            principal_id=ACTOR,
            active=True,
            expected_generation=1,
        ),
    )
    visible = await case.reader.bounded_artifact(
        scope(),
        identity(ACTOR),
        case.output.artifact_revision_id,
        start_byte=0,
        max_bytes=16384,
        include_history=False,
    )
    assert visible.data_classification == "confidential"
    assert case.private.resource_id in {row.resource_id for row in visible.contributors}
    await ResourceAccessStore(provenance_factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=case.private,
            principal_id=ACTOR,
            active=False,
            expected_generation=2,
        ),
    )
    with pytest.raises(ValueError):
        await case.reader.bounded_artifact(
            scope(),
            identity(ACTOR),
            case.output.artifact_revision_id,
            start_byte=0,
            max_bytes=16384,
            include_history=False,
        )


async def test_resource_constraint_filters_source_before_search_rank(
    provenance_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await metadata_scenario(provenance_factory, tmp_path)
    async with brain_transaction(provenance_factory, owner_scope(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        session.add(
            BrainArtifactResourceInput(
                company_id=COMPANY,
                artifact_revision_id=case.source_artifact.artifact_revision_id,
                resource_id=case.private.resource_id,
            )
        )
    found = await case.search.search(
        scope(), identity(ACTOR), SearchRequest(company_id=COMPANY, query="needle")
    )
    assert found.handles == ()


async def test_cycles_cannot_be_read_as_public_provenance(
    provenance_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    case = await metadata_scenario(provenance_factory, tmp_path)
    async with brain_transaction(provenance_factory, owner_scope(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        session.add(
            BrainArtifactInput(
                company_id=COMPANY,
                artifact_revision_id=case.parent.artifact_revision_id,
                input_artifact_revision_id=case.output.artifact_revision_id,
            )
        )
    async with brain_transaction(provenance_factory, owner_scope(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        with pytest.raises(ValueError, match="cyclic"):
            await artifact_input_closure(
                session, owner_scope(), (case.output.artifact_revision_id,)
            )


@pytest.mark.parametrize("path", ["bytes", "search"])
async def test_unqualified_input_leaf_cannot_borrow_valid_output_origin(
    provenance_factory: async_sessionmaker[AsyncSession], tmp_path: Path, path: str
) -> None:
    case = await metadata_scenario(provenance_factory, tmp_path)
    resource = ResourceRef(company_id=COMPANY, resource_id=uuid4())
    await ArtifactTargetStore(provenance_factory).provision(
        owner_scope(), identity(OWNER), resource, readers=(OWNER, ACTOR)
    )
    raw = b"unqualified legacy fragment"
    leaf = ArtifactRevisionRef(
        company_id=COMPANY,
        artifact_id=uuid4(),
        artifact_revision_id=uuid4(),
        revision="fixture-v1",
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
    )
    blobs = ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1")
    await blobs.save(leaf, raw)
    async with brain_transaction(provenance_factory, owner_scope(), identity(OWNER)) as (
        session,
        _,
        now,
    ):
        session.add(
            BrainArtifactRevision(
                **leaf.model_dump(exclude={"schema_version"}),
                resource_id=resource.resource_id,
                media_type="text/plain",
                storage_symbol=blobs.storage_symbol,
                raw_text=raw.decode(),
                recorded_at=now,
                derivation_id=None,
                data_classification=None,
            )
        )
        await session.flush()
        target = case.source_artifact if path == "search" else case.output
        session.add(
            BrainArtifactInput(
                company_id=COMPANY,
                artifact_revision_id=target.artifact_revision_id,
                input_artifact_revision_id=leaf.artifact_revision_id,
            )
        )
    if path == "search":
        found = await case.search.search(
            scope(), identity(ACTOR), SearchRequest(company_id=COMPANY, query="needle")
        )
        assert found.handles == ()
    else:
        # Give the other valid input so only the unqualified leaf causes denial.
        await ResourceAccessStore(provenance_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=case.private,
                principal_id=ACTOR,
                active=True,
                expected_generation=1,
            ),
        )
        with pytest.raises(ValueError, match="qualified source origin"):
            await case.reader.bounded_artifact(
                scope(),
                identity(ACTOR),
                case.output.artifact_revision_id,
                start_byte=0,
                max_bytes=16384,
                include_history=False,
            )
