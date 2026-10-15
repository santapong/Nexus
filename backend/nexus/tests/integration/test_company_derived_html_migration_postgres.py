"""Future restricted-PG MIME/provenance conformance only; never native P/C permission proof.

This exact fresh database is retained, including committed HTML and failed-downgrade evidence.
No fixture teardown deletes history or removes the profile.
"""

import asyncio
import hashlib
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command as alembic_command
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.artifact_input_models import BrainArtifactInput, BrainArtifactResourceInput
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.claims import DerivationRecord
from nexus.company.brain.derivation_support import save_derivation
from nexus.company.brain.event_store import append_event
from nexus.company.brain.models import BrainArtifactRevision, BrainEvidence
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.brain.sources import ArtifactRevisionRef, EvidenceRef, IngestReceipt
from nexus.company.management.artifact_target_store import ArtifactTargetStore
from nexus.settings import settings
from nexus.tests.integration.test_company_brain_ingestion import (
    Reader,
    command,
    configured,
    owner_scope,
)
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_profile_migrations import profile_config

TABLES = (
    "company_brain_artifact_revisions",
    "company_brain_derivations",
    "company_brain_derivation_sources",
    "company_brain_derivation_evidence",
    "company_brain_artifact_inputs",
    "company_brain_artifact_resource_inputs",
    "company_brain_events",
    "company_brain_sources",
    "company_brain_source_revisions",
    "company_brain_evidence",
)


def install016(connection: Connection) -> None:
    """Only normal independent migration operations in an originally empty disposable DB."""
    assert inspect(connection).get_table_names() == []
    connection.execute(text("CREATE TABLE legacy_html_marker (id integer PRIMARY KEY, value text)"))
    connection.execute(text("INSERT INTO legacy_html_marker VALUES (1, 'preserve')"))
    connection.execute(text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)"))
    connection.execute(text("INSERT INTO alembic_version VALUES ('legacy-sentinel')"))
    config = profile_config(connection)
    alembic_command.upgrade(config, "company_016")
    alembic_command.upgrade(config, "company_016")
    connection.execute(text("GRANT USAGE ON SCHEMA public TO nexus_company_app"))
    connection.execute(
        text("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO nexus_company_app")
    )


def downgrade015(connection: Connection) -> None:
    alembic_command.downgrade(profile_config(connection), "company_015")


def reference(raw: bytes) -> ArtifactRevisionRef:
    return ArtifactRevisionRef(
        company_id=COMPANY,
        artifact_id=uuid4(),
        artifact_revision_id=uuid4(),
        revision="schema-only-v1",
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
    )


def artifact(
    ref: ArtifactRevisionRef,
    resource: ResourceRef,
    raw: bytes,
    media: str,
    derivation: UUID | None = None,
) -> BrainArtifactRevision:
    return BrainArtifactRevision(
        **ref.model_dump(exclude={"schema_version"}),
        resource_id=resource.resource_id,
        raw_text=raw.decode(),
        media_type=media,
        storage_symbol="fixture.blobs.v1",
        derivation_id=derivation,
        data_classification="internal",
    )


async def complete_graph(
    factory: async_sessionmaker[AsyncSession],
    source: IngestReceipt,
    target: ResourceRef,
    raw: bytes,
    output: ArtifactRevisionRef,
) -> UUID:
    """Commit all graph families through actual restricted inserts and same-company FKs."""
    async with brain_transaction(factory, owner_scope(), identity(OWNER)) as (session, _, now):
        evidence = tuple(
            (
                await session.scalars(
                    select(BrainEvidence)
                    .where(
                        BrainEvidence.company_id == COMPANY,
                        BrainEvidence.source_revision_id == source.source.source_revision_id,
                    )
                    .limit(33)
                )
            ).all()
        )
        assert 0 < len(evidence) <= 32
        key = uuid4()
        session.add(artifact(output, target, raw, "text/html", key))
        await session.flush()
        await save_derivation(
            session,
            DerivationRecord(
                company_id=COMPANY,
                derivation_id=key,
                artifact=output,
                kind="presentation",
                recipe_version="schema.derived-html.v1",
                contributors=(source.source,),
                evidence=tuple(
                    EvidenceRef(company_id=COMPANY, evidence_id=row.evidence_id) for row in evidence
                ),
                recorded_at=now,
            ),
        )
        session.add(
            BrainArtifactInput(
                company_id=COMPANY,
                artifact_revision_id=output.artifact_revision_id,
                input_artifact_revision_id=source.artifact.artifact_revision_id,
            )
        )
        source_resource = await session.scalar(
            text(
                "SELECT resource_id FROM company_brain_sources "
                "WHERE company_id=:company AND source_id=:source"
            ),
            {"company": COMPANY, "source": source.source.source_id},
        )
        assert isinstance(source_resource, UUID)
        session.add(
            BrainArtifactResourceInput(
                company_id=COMPANY,
                artifact_revision_id=output.artifact_revision_id,
                resource_id=source_resource,
            )
        )
        await append_event(
            session,
            owner_scope(),
            kind="derivation_changed",
            resource_id=target.resource_id,
            deduplication_key=f"schema.derived-html:{output.artifact_revision_id}",
            now=now,
        )
        await session.flush()
        # Exercise both directions of the deferred artifact/derivation graph before actual commit.
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    return key


async def snapshot(connection: AsyncConnection) -> tuple[object, ...]:
    """Compare schema-only rows, DDL, head and legacy state across a failed downgrade."""
    values: list[object] = []
    for table in TABLES:
        rows = tuple(
            (
                await connection.scalars(
                    text(f'SELECT to_jsonb(t)::text FROM "{table}" AS t ORDER BY to_jsonb(t)::text')
                )
            ).all()
        )
        values.append((table, rows))
    for query in (
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname='ck_brain_artifact_media' "
        "AND conrelid='company_brain_artifact_revisions'::regclass",
        "SELECT version_num FROM company_alembic_version",
        "SELECT value FROM legacy_html_marker",
        "SELECT version_num FROM alembic_version",
    ):
        values.append(await connection.scalar(text(query)))
    return tuple(values)


async def test_normal016_commits_derived_html_and_refuses_evidence_losing_downgrade(
    tmp_path: Path,
) -> None:
    if not settings.company_test_database_url:
        pytest.skip("Explicit fresh derived-HTML test database is not configured")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_derived_html_v1"
    assert settings.company_test_database_url != settings.database_url
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    factory = async_sessionmaker(app, expire_on_commit=False)
    try:
        async with asyncio.timeout(180):
            async with admin.begin() as connection:
                await connection.run_sync(install016)
            async with factory() as session:
                assert await session.scalar(text("SELECT current_user")) == "nexus_company_app"
                assert (
                    await session.scalar(
                        text(
                            "SELECT rolsuper OR rolbypassrls FROM pg_roles "
                            "WHERE rolname=current_user"
                        )
                    )
                    is False
                )
            raw_source = b"Real schema-only provenance input; no native work receipt is asserted."
            ingestion = await configured(factory, tmp_path, Reader({"r1": raw_source}))
            received = await ingestion.ingest(
                owner_scope(), identity(OWNER), command(raw_source, "r1")
            )
            assert received.status == "accepted"
            target = ResourceRef(company_id=COMPANY, resource_id=uuid4())
            await ArtifactTargetStore(factory).provision(
                owner_scope(), identity(OWNER), target, readers=(OWNER,)
            )
            html = b"<!doctype html><html><body><p>Schema-only derived export.</p></body></html>"
            output = reference(html)
            await ingestion._blobs.save(output, html)
            derivation = await complete_graph(factory, received, target, html, output)
            reader = BoundedArtifactReader(factory, ingestion._blobs)
            body = await reader.bounded_artifact(
                owner_scope(),
                identity(OWNER),
                output.artifact_revision_id,
                start_byte=0,
                max_bytes=16384,
                include_history=False,
            )
            assert body.artifact == output and body.text.encode() == html and not body.has_more
            for media in ("text/plain", "text/markdown", "application/json"):
                raw = (
                    b"{}"
                    if media == "application/json"
                    else b"Original direct format remains valid."
                )
                async with brain_transaction(factory, owner_scope(), identity(OWNER)) as (
                    session,
                    _,
                    _,
                ):
                    session.add(artifact(reference(raw), target, raw, media))
            for media, parent in (
                ("text/html", None),
                ("image/svg+xml", None),
                ("image/svg+xml", derivation),
                ("application/javascript", derivation),
                ("text/html; charset=utf-8", derivation),
            ):
                with pytest.raises(DBAPIError, match="ck_brain_artifact_media"):
                    async with brain_transaction(factory, owner_scope(), identity(OWNER)) as (
                        session,
                        _,
                        _,
                    ):
                        session.add(artifact(reference(html), target, html, media, parent))
                        await session.flush()
            with pytest.raises(DBAPIError, match="fk_brain_artifact_derivation"):
                async with brain_transaction(factory, owner_scope(), identity(OWNER)) as (
                    session,
                    _,
                    _,
                ):
                    session.add(artifact(reference(html), target, html, "text/html", uuid4()))
                    await session.flush()
                    await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            async with admin.begin() as connection:
                await connection.execute(
                    select(func.set_config("nexus.company_id", str(COMPANY), True))
                )
                before = await snapshot(connection)
                assert before[-3:] == ("company_016", "preserve", "legacy-sentinel")
                with pytest.raises(DBAPIError, match="ck_brain_artifact_media"):
                    async with connection.begin_nested():
                        await connection.run_sync(downgrade015)
                assert await snapshot(connection) == before
                assert (
                    await connection.scalar(
                        text(
                            "SELECT count(*) FROM company_brain_artifact_revisions "
                            "WHERE media_type='text/html'"
                        )
                    )
                    == 1
                )
                total = await connection.scalar(
                    select(func.count()).select_from(BrainArtifactRevision)
                )
                assert isinstance(total, int) and total >= 5
    finally:
        # Retain all committed source/HTML/history and the profile, including on failure.
        await app.dispose()
        await admin.dispose()
