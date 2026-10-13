"""Actual bytes and current owner/resource/head rechecks precede any claim publication."""

from pathlib import Path
from uuid import UUID, uuid5

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.blob_store import BlobReader
from nexus.company.brain.claim_models import BrainClaimRevision
from nexus.company.brain.claim_store import BrainClaimStore
from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.publication_contracts import ClaimPublicationBatch
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.tests.brain_publication_support import actor_scope, sources
from nexus.tests.brain_publication_support import publication_factory as publication_factory
from nexus.tests.integration.test_company_brain_claim_publication import publication
from nexus.tests.integration.test_company_brain_ingestion import (
    RESOURCE,
    SOURCE,
    Reader,
    command,
    configured,
    owner_scope,
)
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control, work
from nexus.tests.integration.test_company_execution_store import identity


@pytest.mark.parametrize("change", ["owner", "resource", "head", "bytes"])
async def test_revocation_or_changed_proof_during_blob_read_never_publishes_claim(
    publication_factory: async_sessionmaker[AsyncSession], tmp_path: Path, change: str
) -> None:
    retriever, evidence = await sources(publication_factory, tmp_path)

    class ChangingReader:
        def __init__(self, original: BlobReader) -> None:
            self.original, self.changed = original, False

        async def read(self, artifact: ArtifactRevisionRef) -> bytes:
            raw = await self.original.read(artifact)
            if self.changed:
                return raw
            self.changed = True
            if change == "owner":
                await PersistentCompanyDirectory(publication_factory).set_membership(
                    MembershipChange(
                        company_id=COMPANY,
                        principal_id=OWNER,
                        role="owner",
                        membership_active=False,
                    ),
                    control(),
                )
            elif change == "resource":
                await ResourceAccessStore(publication_factory).change(
                    owner_scope(),
                    identity(OWNER),
                    ResourceAccessChange(
                        company_id=COMPANY,
                        resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                        principal_id=OWNER,
                        active=False,
                        expected_generation=1,
                    ),
                )
            elif change == "head":
                raw2 = b"new registered source revision"
                next_store = await configured(publication_factory, tmp_path, Reader({"r2": raw2}))
                await next_store.ingest(
                    owner_scope(),
                    identity(OWNER),
                    command(raw2, "r2", uuid5(SOURCE, "source-revision-v1:r1")),
                )
            else:
                return b"unverified replacement bytes"
            return raw

    scoped = PersistentBrainRetriever(
        publication_factory, ChangingReader(retriever.blobs), limits=retriever.limits
    )
    with pytest.raises((BrainDeniedError, BrainConflictError)):
        await BrainClaimStore(publication_factory, scoped).publish_manual(
            owner_scope(), identity(OWNER), publication(evidence), source_report=True
        )
    async with publication_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(BrainClaimRevision)) == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BrainEvent)
                .where(BrainEvent.kind == "claims_changed")
            )
            == 0
        )


async def test_later_failed_batch_member_rolls_back_claims_heads_and_events(
    publication_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    retriever, evidence = await sources(publication_factory, tmp_path)
    await PersistentCompanyDirectory(publication_factory).register_work(work(), control())
    first = publication(evidence)
    second = first.model_copy(
        update={
            "draft": first.draft.model_copy(update={"claim_id": UUID(int=3301)}),
            "expected_previous_revision_id": UUID(int=9999),
        }
    )
    with pytest.raises(BrainConflictError):
        await BrainClaimStore(publication_factory, retriever).propose_batch(
            actor_scope(),
            identity(ACTOR),
            ClaimPublicationBatch(
                company_id=COMPANY,
                extraction_version="fixture.extraction.v1",
                claims=(first, second),
            ),
        )
    async with publication_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(BrainClaimRevision)) == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BrainEvent)
                .where(BrainEvent.kind == "claims_changed")
            )
            == 0
        )
