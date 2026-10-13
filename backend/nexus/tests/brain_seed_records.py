"""Evaluator-only exact provenance row construction; no completed/authority/budget writes."""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.models import (
    BrainArtifactRevision,
    BrainChunk,
    BrainEvidence,
    BrainParseRevision,
    BrainSource,
    BrainSourceHead,
    BrainSourceRevision,
)
from nexus.tests.brain_catalog_fixtures import ArtifactFixture, FixtureCatalog, fixture_id
from nexus.tests.brain_source_fixtures import SourceFixture, SourcePack


def resource_for(artifact: ArtifactFixture, pack: SourcePack) -> UUID:
    source = next(
        (
            row
            for row in pack.source_revisions
            if row.source_revision_id == artifact.source_revision_id
        ),
        None,
    )
    return (
        source.acl_resource_id if source else fixture_id("artifact-resource", artifact.artifact_id)
    )


def derivation_for(
    artifact: ArtifactFixture, pack: SourcePack, catalog: FixtureCatalog
) -> UUID | None:
    direct = next(
        (
            row.derivation_id
            for row in catalog.derivations
            if row.artifact_id == artifact.artifact_id
        ),
        None,
    )
    if direct is not None:
        return direct
    source = next(
        (
            row
            for row in pack.source_revisions
            if row.source_revision_id == artifact.source_revision_id
        ),
        None,
    )
    if source is None or source.authority.get("tier") != "summary":
        return None
    targets = {row.artifact_id: row for row in catalog.artifacts}
    return next(
        (
            row.derivation_id
            for row in catalog.derivations
            if row.company_id == source.company_id
            and row.case_id == source.case_id
            and targets[row.artifact_id].text == source.text
        ),
        None,
    )


def artifact_row(
    artifact: ArtifactFixture, pack: SourcePack, catalog: FixtureCatalog
) -> BrainArtifactRevision:
    ref = artifact.reference()
    return BrainArtifactRevision(
        company_id=artifact.company_id,
        artifact_revision_id=ref.artifact_revision_id,
        artifact_id=artifact.artifact_id,
        revision=artifact.revision,
        resource_id=resource_for(artifact, pack),
        media_type="text/plain",
        storage_symbol="fixture.blobs.v1",
        raw_text=artifact.text,
        sha256=artifact.sha256,
        byte_length=artifact.byte_length,
        derivation_id=derivation_for(artifact, pack, catalog),
    )


def source_row(source: SourceFixture) -> BrainSource:
    return BrainSource(
        company_id=source.company_id,
        source_id=source.source_id,
        resource_id=source.acl_resource_id,
        source_symbol=source.source_symbol,
        external_key=source.external_key,
        authority_profile=f"fixture.{source.authority['tier']}.v1",
        data_classification="internal",
        recorded_by=source.author_id,
        recorded_at=source.ingested_at,
    )


def revision_row(
    source: SourceFixture, artifact: ArtifactFixture, pack: SourcePack, catalog: FixtureCatalog
) -> BrainSourceRevision:
    return BrainSourceRevision(
        company_id=source.company_id,
        source_id=source.source_id,
        source_revision_id=source.source_revision_id,
        revision=source.revision,
        artifact_revision_id=artifact.reference().artifact_revision_id,
        source_event_precision=source.source_event.precision,
        source_event_value=source.source_event.value,
        source_event_basis=source.source_event.basis,
        ingested_at=source.ingested_at,
        recorded_by=source.author_id,
        source_author=str(source.author_id),
        derivation_id=derivation_for(artifact, pack, catalog),
    )


async def seed_parse_evidence(
    session: AsyncSession, source: SourceFixture, artifact: ArtifactFixture, pack: SourcePack
) -> None:
    raw = source.text.encode()
    parse_id, chunk_id = (
        fixture_id(kind, source.source_revision_id) for kind in ("parse", "chunk")
    )
    session.add(
        BrainParseRevision(
            company_id=source.company_id,
            parse_revision_id=parse_id,
            source_revision_id=source.source_revision_id,
            parser_version="fixture.utf8-span.v1",
            chunker_version="fixture.utf8-span.v1",
            canonical_text=source.text,
            canonical_sha256=source.sha256,
            recorded_at=source.ingested_at,
        )
    )
    await session.flush()
    session.add(
        BrainChunk(
            company_id=source.company_id,
            chunk_id=chunk_id,
            parse_revision_id=parse_id,
            source_revision_id=source.source_revision_id,
            ordinal=0,
            start_byte=0,
            end_byte=len(raw),
            text=source.text,
            sha256=source.sha256,
            search_config="simple",
            search_vector=func.to_tsvector("simple", source.text),
        )
    )
    await session.flush()
    await _seed_evidence(session, source, artifact, pack)


async def _seed_evidence(
    session: AsyncSession, source: SourceFixture, artifact: ArtifactFixture, pack: SourcePack
) -> None:
    raw = source.text.encode()
    parse_id, chunk_id = (
        fixture_id(kind, source.source_revision_id) for kind in ("parse", "chunk")
    )
    for evidence in pack.evidence:
        if evidence.source_revision_id != source.source_revision_id:
            continue
        span = evidence.locator
        if hashlib.sha256(raw[span.start_byte : span.end_byte]).hexdigest() != evidence.span_sha256:
            raise ValueError("Frozen evidence span hash mismatch")
        session.add(
            BrainEvidence(
                company_id=source.company_id,
                evidence_id=evidence.evidence_id,
                source_id=source.source_id,
                source_revision_id=source.source_revision_id,
                artifact_revision_id=artifact.reference().artifact_revision_id,
                raw_start_byte=span.start_byte,
                raw_end_byte=span.end_byte,
                raw_section=span.section,
                span_sha256=evidence.span_sha256,
                parse_revision_id=parse_id,
                parsed_start_byte=span.start_byte,
                parsed_end_byte=span.end_byte,
                chunk_id=chunk_id,
            )
        )
    await session.flush()


async def seed_heads(
    session: AsyncSession, company_id: UUID, case_id: str, catalog: FixtureCatalog
) -> None:
    for head in catalog.source_heads:
        if (head.company_id, head.case_id) == (company_id, case_id):
            session.add(
                BrainSourceHead(
                    company_id=company_id,
                    source_id=head.source_id,
                    current_revision_id=head.current_revision_id,
                    generation=1,
                    observed_at=head.as_of,
                    fresh_until=None,
                    availability=head.availability,
                )
            )
    await session.flush()
