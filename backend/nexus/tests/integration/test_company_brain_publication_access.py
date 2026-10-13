"""Publishing sourced knowledge cannot broaden current recipient ACL or classification."""

import hashlib
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import SourceTime
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.claim_store import BrainClaimStore
from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.evidence_models import BrainEvidence
from nexus.company.brain.ingestion_store import BrainIngestionStore
from nexus.company.brain.publication_contracts import ClaimLinkPublication
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry, SourceSnapshot
from nexus.company.brain.sources import (
    ArtifactRevisionRef,
    EvidenceRef,
    IngestCommand,
    SourceRegistration,
)
from nexus.tests.brain_publication_support import publication_factory as publication_factory
from nexus.tests.brain_publication_support import sources
from nexus.tests.integration.test_company_brain_claim_publication import publication
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity


@pytest.mark.parametrize("problem", ["none", "recipient", "classification"])
async def test_output_reader_intersection_and_server_source_classification(
    publication_factory: async_sessionmaker[AsyncSession], tmp_path: Path, problem: str
) -> None:
    retriever, _ = await sources(publication_factory, tmp_path)
    raw = b"private source-reported content"
    source_id = UUID(int=3401)

    class PrivateReader:
        async def read(self, source: SourceRegistration, revision: str) -> SourceSnapshot:
            return SourceSnapshot(
                company_id=COMPANY,
                source_id=source_id,
                source_symbol="fixture.private.v1",
                external_key="private-1",
                revision=revision,
                raw_bytes=raw,
                source_event=SourceTime(precision="unknown", value=None, basis="private source"),
            )

    policy = SourcePolicy(
        source_symbol="fixture.private.v1",
        authority_profile="fixture.reported.v1",
        data_classification="confidential" if problem == "classification" else "internal",
        media_type="text/plain",
        parser_version="utf8-identity-v1",
        chunker_version="utf8-sections-v1",
        search_config="simple",
        freshness_seconds=None,
        allowed_external_keys=frozenset({"private-1"}),
    )
    store = BrainIngestionStore(
        publication_factory,
        SourceRegistry((policy,), PrivateReader()),
        ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1"),
    )
    await store.register(
        owner_scope(),
        identity(OWNER),
        SourceRegistration(
            company_id=COMPANY,
            source_id=source_id,
            resource=ResourceRef(company_id=COMPANY, resource_id=UUID(int=3402)),
            source_symbol=policy.source_symbol,
            external_key="private-1",
        ),
        readers=(OWNER,) if problem == "recipient" else (OWNER, ACTOR),
    )
    await store.ingest(
        owner_scope(),
        identity(OWNER),
        IngestCommand(
            company_id=COMPANY,
            source_id=source_id,
            revision="r1",
            artifact=ArtifactRevisionRef(
                company_id=COMPANY,
                artifact_id=UUID(int=3403),
                artifact_revision_id=UUID(int=3404),
                revision="r1",
                sha256=hashlib.sha256(raw).hexdigest(),
                byte_length=len(raw),
            ),
        ),
    )
    async with publication_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        key = await session.scalar(
            select(BrainEvidence.evidence_id).where(BrainEvidence.source_id == source_id)
        )
        assert key is not None
    claim_store = BrainClaimStore(publication_factory, retriever)
    selected = EvidenceRef(company_id=COMPANY, evidence_id=key)
    if problem == "none":
        original = await claim_store.publish_manual(
            owner_scope(), identity(OWNER), publication(selected), source_report=True
        )
        newer_command = publication(selected).model_copy(
            update={
                "resource": ResourceRef(company_id=COMPANY, resource_id=UUID(int=3402)),
                "draft": publication(selected).draft.model_copy(
                    update={"claim_id": UUID(int=3999)}
                ),
            }
        )
        newer = await claim_store.publish_manual(
            owner_scope(), identity(OWNER), newer_command, source_report=True
        )
        link = await claim_store.link(
            owner_scope(),
            identity(OWNER),
            ClaimLinkPublication(
                company_id=COMPANY,
                link_id=UUID(int=3998),
                subject=newer,
                object=original,
                predicate="supersedes",
                rationale="Both immutable claim resources change their read projection",
                evidence=(selected,),
            ),
        )
        async with publication_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            changed = set(
                (
                    await session.scalars(
                        select(BrainEvent.resource_id).where(
                            BrainEvent.deduplication_key.startswith(f"claim-link:{link.link_id}")
                        )
                    )
                ).all()
            )
            assert changed == {RESOURCE, UUID(int=3402)}
        return
    with pytest.raises(BrainDeniedError):
        await claim_store.publish_manual(
            owner_scope(),
            identity(OWNER),
            publication(EvidenceRef(company_id=COMPANY, evidence_id=key)),
            source_report=True,
        )
