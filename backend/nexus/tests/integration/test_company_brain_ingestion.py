"""Normal-profile protected-byte ingestion, quarantine and CAS in its assigned private DB."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid5

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.access import AccessDeniedError
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import BrainReadScope, SourceTime
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.ingestion_store import BrainIngestionStore
from nexus.company.brain.scope_support import BrainConflictError
from nexus.company.brain.source_models import BrainSourceHead, BrainSourceRevision
from nexus.company.brain.source_registry import SourcePolicy, SourceRegistry, SourceSnapshot
from nexus.company.brain.sources import ArtifactRevisionRef, IngestCommand, SourceRegistration
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    WORKSPACE,
    control,
    migrate,
    prepare,
)
from nexus.tests.integration.test_company_execution_store import identity

SOURCE, RESOURCE, ARTIFACT = UUID(int=1000), UUID(int=1001), UUID(int=1002)


def owner_scope() -> BrainReadScope:
    return BrainReadScope(
        company_id=COMPANY,
        workspace_id=WORKSPACE,
        principal_id=OWNER,
        operation_id=UUID(int=1003),
        trace_id=UUID(int=1004),
    )


class Reader:
    def __init__(self, snapshots: dict[str, bytes]) -> None:
        self.snapshots = snapshots

    async def read(self, source: SourceRegistration, revision: str) -> SourceSnapshot:
        return SourceSnapshot(
            company_id=COMPANY,
            source_id=SOURCE,
            source_symbol="fixture.source.v1",
            external_key="document-1",
            revision=revision,
            raw_bytes=self.snapshots[revision],
            source_event=SourceTime(precision="day", value="2026-10-13", basis="declared fixture"),
        )


async def configured(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    reader: Reader,
    *,
    media: str = "text/plain",
) -> BrainIngestionStore:
    await prepare(factory)
    policy = SourcePolicy.model_validate(
        {
            "source_symbol": "fixture.source.v1",
            "authority_profile": "fixture.reported.v1",
            "data_classification": "internal",
            "media_type": media,
            "parser_version": "utf8-identity-v1",
            "chunker_version": "utf8-sections-v1",
            "search_config": "simple",
            "freshness_seconds": 3600,
            "allowed_external_keys": frozenset({"document-1"}),
        }
    )
    store = BrainIngestionStore(
        factory,
        SourceRegistry((policy,), reader),
        ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1"),
    )
    await store.register(
        owner_scope(),
        identity(OWNER),
        SourceRegistration(
            company_id=COMPANY,
            source_id=SOURCE,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            source_symbol="fixture.source.v1",
            external_key="document-1",
        ),
        readers=(OWNER, ACTOR),
    )
    return store


def command(raw: bytes, revision: str, previous: UUID | None = None) -> IngestCommand:
    return IngestCommand(
        company_id=COMPANY,
        source_id=SOURCE,
        revision=revision,
        artifact=ArtifactRevisionRef(
            company_id=COMPANY,
            artifact_id=ARTIFACT,
            artifact_revision_id=uuid5(ARTIFACT, revision),
            revision=revision,
            sha256=hashlib.sha256(raw).hexdigest(),
            byte_length=len(raw),
        ),
        expected_previous_revision_id=previous,
    )


@pytest.fixture
async def ingest_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_brain_ingest"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
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


async def test_exact_duplicate_retains_source_parse_and_evidence_identity(
    ingest_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    raw = "raw ไทย\r\ncompany 🚀\n".encode()
    store = await configured(ingest_factory, tmp_path, Reader({"r1": raw}))
    first = await store.ingest(owner_scope(), identity(OWNER), command(raw, "r1"))
    assert first.status == "accepted"
    assert await store.ingest(owner_scope(), identity(OWNER), command(raw, "r1")) == first
    async with ingest_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(BrainSourceRevision)) == 1
        head = await session.get(BrainSourceHead, (COMPANY, SOURCE))
        assert head is not None and head.current_revision_id == first.source.source_revision_id
        assert head.generation == 1 and head.availability == "available"


async def test_malformed_json_quarantines_raw_and_keeps_previous_good_history(
    ingest_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    good, bad = b'{ "raw": 1 }\n', b'{ "invalid":'
    store = await configured(
        ingest_factory, tmp_path, Reader({"r1": good, "r2": bad}), media="application/json"
    )
    first = await store.ingest(owner_scope(), identity(OWNER), command(good, "r1"))
    failed = await store.ingest(
        owner_scope(), identity(OWNER), command(bad, "r2", first.source.source_revision_id)
    )
    assert failed.status == "quarantined" and failed.reason_code == "invalid_json"
    async with ingest_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(BrainSourceRevision)) == 2
        head = await session.get(BrainSourceHead, (COMPANY, SOURCE))
        assert head is not None and head.availability == "quarantined"


async def test_same_external_revision_different_bytes_conflicts_without_overwrite(
    ingest_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    reader = Reader({"r1": b"initial bytes"})
    store = await configured(ingest_factory, tmp_path, reader)
    original = await store.ingest(
        owner_scope(), identity(OWNER), command(reader.snapshots["r1"], "r1")
    )
    reader.snapshots["r1"] = b"changed bytes"
    conflict = await store.ingest(
        owner_scope(), identity(OWNER), command(reader.snapshots["r1"], "r1")
    )
    assert conflict.status == "conflict" and conflict.artifact == original.artifact
    assert (
        await ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1").read(
            original.artifact
        )
        == b"initial bytes"
    )


async def test_concurrent_head_cas_publishes_once_and_leaves_only_unreferenced_loser_blob(
    ingest_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    ready_event = asyncio.Event()

    class RacingReader(Reader):
        count = 0

        async def read(self, source: SourceRegistration, revision: str) -> SourceSnapshot:
            self.count += 1
            if self.count == 2:
                ready_event.set()
            await ready_event.wait()
            return await super().read(source, revision)

    reader = RacingReader({"r1": b"first", "r2": b"second"})
    store = await configured(ingest_factory, tmp_path, reader)
    outcomes = await asyncio.gather(
        *(
            store.ingest(owner_scope(), identity(OWNER), command(raw, revision))
            for revision, raw in reader.snapshots.items()
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(value, BrainConflictError) for value in outcomes) == 1
    assert sum(not isinstance(value, BaseException) for value in outcomes) == 1
    async with ingest_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(BrainSourceRevision)) == 1
        head = await session.get(BrainSourceHead, (COMPANY, SOURCE))
        assert head is not None and head.generation == 1


async def test_owner_revocation_during_source_read_denies_publication_after_parse(
    ingest_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    class RevokingReader(Reader):
        async def read(self, source: SourceRegistration, revision: str) -> SourceSnapshot:
            await PersistentCompanyDirectory(ingest_factory).set_membership(
                MembershipChange(
                    company_id=COMPANY, principal_id=OWNER, role="owner", membership_active=False
                ),
                control(),
            )
            return await super().read(source, revision)

    raw = b"preserved orphan is not a committed source"
    store = await configured(ingest_factory, tmp_path, RevokingReader({"r1": raw}))
    with pytest.raises(AccessDeniedError):
        await store.ingest(owner_scope(), identity(OWNER), command(raw, "r1"))
    async with ingest_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(BrainSourceRevision)) == 0


@pytest.mark.parametrize("unsupported", [b"bad\xff", b"has\x00nul"])
async def test_unsupported_utf8_or_nul_rejects_before_blob_refs_or_head_change(
    ingest_factory: async_sessionmaker[AsyncSession], tmp_path: Path, unsupported: bytes
) -> None:
    store = await configured(ingest_factory, tmp_path, Reader({"r1": unsupported}))
    with pytest.raises(ValueError):
        await store.ingest(owner_scope(), identity(OWNER), command(unsupported, "r1"))
    assert not tuple(tmp_path.rglob("*.blob"))


async def test_historical_quarantine_replay_retains_original_failure_without_head_rollback(
    ingest_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    reader = Reader({"r1": b'{"ok":1}', "r2": b'{"bad":', "r3": b'{"ok":3}'})
    store = await configured(ingest_factory, tmp_path, reader, media="application/json")
    first = await store.ingest(
        owner_scope(), identity(OWNER), command(reader.snapshots["r1"], "r1")
    )
    failed = await store.ingest(
        owner_scope(),
        identity(OWNER),
        command(reader.snapshots["r2"], "r2", first.source.source_revision_id),
    )
    latest = await store.ingest(
        owner_scope(),
        identity(OWNER),
        command(reader.snapshots["r3"], "r3", failed.source.source_revision_id),
    )
    replay = await store.ingest(
        owner_scope(), identity(OWNER), command(reader.snapshots["r2"], "r2")
    )
    assert replay == failed
    async with ingest_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        head = await session.get(BrainSourceHead, (COMPANY, SOURCE))
        assert head is not None and head.current_revision_id == latest.source.source_revision_id
