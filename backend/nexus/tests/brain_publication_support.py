"""Assigned normal-profile PG fixture with actual source/blob/citation prerequisites."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.evidence_models import BrainEvidence
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.sources import EvidenceRef
from nexus.settings import settings
from nexus.tests.integration.test_company_brain_ingestion import (
    Reader,
    command,
    configured,
    owner_scope,
)
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    TASK,
    TRACE,
    migrate,
)
from nexus.tests.integration.test_company_execution_store import identity


@pytest.fixture
async def publication_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_brain_publication"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    migrated = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        migrated = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if migrated:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


async def sources(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> tuple[PersistentBrainRetriever, EvidenceRef]:
    raw = b"Source-reported product state: active. Historical claim: pending."
    store = await configured(factory, root, Reader({"r1": raw}))
    await store.ingest(owner_scope(), identity(OWNER), command(raw, "r1"))
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        evidence_id = await session.scalar(select(BrainEvidence.evidence_id))
        assert evidence_id is not None
    return (
        PersistentBrainRetriever(
            factory,
            ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"),
            limits=RetrievalLimits(),
        ),
        EvidenceRef(company_id=COMPANY, evidence_id=evidence_id),
    )


def actor_scope() -> BrainReadScope:
    return owner_scope().model_copy(
        update={
            "principal_id": ACTOR,
            "task_id": TASK,
            "task_trace_id": TRACE,
            "actor_id": ACTOR,
            "operation_id": UUID(int=3000),
        }
    )
