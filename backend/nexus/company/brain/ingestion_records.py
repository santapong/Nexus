"""Exact typed projections from immutable source/artifact provenance rows."""

from __future__ import annotations

from sqlalchemy import cast, func, literal
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import SourceTime
from nexus.company.brain.evidence_models import (
    BrainChunk,
    BrainEvidence,
    BrainParseFailure,
    BrainParseRevision,
)
from nexus.company.brain.parser import ParsedSource
from nexus.company.brain.scope_support import BrainConflictError
from nexus.company.brain.source_models import (
    BrainArtifactRevision,
    BrainSource,
    BrainSourceRevision,
)
from nexus.company.brain.sources import (
    ArtifactRevisionRecord,
    ParseFailureRecord,
    SourceRecord,
    SourceRevisionRecord,
)


def source_record(row: BrainSource) -> SourceRecord:
    return SourceRecord.model_validate(
        {
            "company_id": row.company_id,
            "source_id": row.source_id,
            "resource": ResourceRef(company_id=row.company_id, resource_id=row.resource_id),
            "source_symbol": row.source_symbol,
            "external_key": row.external_key,
            "authority_profile": row.authority_profile,
            "data_classification": row.data_classification,
            "recorded_by": row.recorded_by,
            "recorded_at": row.recorded_at,
        }
    )


def artifact_record(row: BrainArtifactRevision) -> ArtifactRevisionRecord:
    return ArtifactRevisionRecord.model_validate(
        {
            "company_id": row.company_id,
            "artifact_id": row.artifact_id,
            "artifact_revision_id": row.artifact_revision_id,
            "revision": row.revision,
            "sha256": row.sha256,
            "byte_length": row.byte_length,
            "resource": ResourceRef(company_id=row.company_id, resource_id=row.resource_id),
            "media_type": row.media_type,
            "storage_symbol": row.storage_symbol,
            "raw_text": row.raw_text,
            "recorded_at": row.recorded_at,
            "derivation_id": row.derivation_id,
        }
    )


def revision_record(
    row: BrainSourceRevision, artifact: ArtifactRevisionRecord
) -> SourceRevisionRecord:
    return SourceRevisionRecord.model_validate(
        {
            "company_id": row.company_id,
            "source_id": row.source_id,
            "source_revision_id": row.source_revision_id,
            "revision": row.revision,
            "artifact": artifact,
            "source_event": SourceTime.model_validate(
                {
                    "precision": row.source_event_precision,
                    "value": row.source_event_value,
                    "basis": row.source_event_basis,
                }
            ),
            "ingested_at": row.ingested_at,
            "recorded_by": row.recorded_by,
            "source_author": row.source_author,
            "derivation_id": row.derivation_id,
        }
    )


async def save_parse(session: AsyncSession, parsed: ParsedSource, search_config: str) -> None:
    """All parser rows are append-only and commit with the current-head CAS/outbox publication."""
    value = parsed.parse
    session.add(
        BrainParseRevision(
            company_id=value.company_id,
            parse_revision_id=value.parse_revision_id,
            source_revision_id=value.source.source_revision_id,
            parser_version=value.parser_version,
            chunker_version=value.chunker_version,
            canonical_text=value.canonical_text,
            canonical_sha256=value.canonical_sha256,
            recorded_at=value.recorded_at,
        )
    )
    await session.flush()
    for chunk in parsed.chunks:
        span = chunk.parsed_span
        session.add(
            BrainChunk(
                company_id=chunk.company_id,
                chunk_id=chunk.chunk_id,
                parse_revision_id=chunk.parse_revision_id,
                source_revision_id=chunk.source.source_revision_id,
                ordinal=chunk.ordinal,
                start_byte=span.start_byte,
                end_byte=span.end_byte,
                section=span.section,
                path=span.path,
                page=span.page,
                text=chunk.text,
                sha256=chunk.sha256,
                search_config=search_config,
                search_vector=func.to_tsvector(cast(literal(search_config), REGCONFIG), chunk.text),
            )
        )
    await session.flush()
    for evidence in parsed.evidence:
        span = evidence.raw_span
        session.add(
            BrainEvidence(
                company_id=evidence.company_id,
                evidence_id=evidence.evidence_id,
                source_id=evidence.source.source_id,
                source_revision_id=evidence.source.source_revision_id,
                artifact_revision_id=evidence.artifact.artifact_revision_id,
                raw_start_byte=span.start_byte,
                raw_end_byte=span.end_byte,
                raw_section=span.section,
                raw_path=span.path,
                raw_page=span.page,
                span_sha256=evidence.span_sha256,
                parse_revision_id=evidence.parse_revision_id,
                parsed_start_byte=span.start_byte,
                parsed_end_byte=span.end_byte,
                chunk_id=evidence.chunk_id,
            )
        )


async def save_failure(session: AsyncSession, failure: ParseFailureRecord) -> None:
    session.add(
        BrainParseFailure(
            company_id=failure.company_id,
            failure_id=failure.failure_id,
            source_id=failure.source.source_id,
            source_revision_id=failure.source.source_revision_id,
            parser_version=failure.parser_version,
            chunker_version=failure.chunker_version,
            reason_code=failure.reason_code,
            recorded_at=failure.recorded_at,
        )
    )


async def save_raw_records(
    session: AsyncSession, artifact: ArtifactRevisionRecord, source: SourceRevisionRecord
) -> None:
    existing = await session.get(
        BrainArtifactRevision, (artifact.company_id, artifact.artifact_revision_id)
    )
    if existing is not None:
        if artifact_record(existing).model_dump(exclude={"recorded_at"}) != artifact.model_dump(
            exclude={"recorded_at"}
        ):
            raise BrainConflictError("Protected artifact identity cannot be rebound")
    else:
        session.add(
            BrainArtifactRevision(
                company_id=artifact.company_id,
                artifact_id=artifact.artifact_id,
                artifact_revision_id=artifact.artifact_revision_id,
                revision=artifact.revision,
                sha256=artifact.sha256,
                byte_length=artifact.byte_length,
                resource_id=artifact.resource.resource_id,
                media_type=artifact.media_type,
                storage_symbol=artifact.storage_symbol,
                raw_text=artifact.raw_text,
                recorded_at=artifact.recorded_at,
                derivation_id=artifact.derivation_id,
            )
        )
        await session.flush()
    prior_source = await session.get(
        BrainSourceRevision,
        {"company_id": source.company_id, "source_revision_id": source.source_revision_id},
    )
    if prior_source is not None:
        # A new parse attempt cannot change original source facts or ingestion metadata.
        prior = revision_record(prior_source, artifact)
        excluded = {"ingested_at", "recorded_by"}
        if prior.model_dump(exclude=excluded) != source.model_dump(exclude=excluded):
            raise BrainConflictError("Source revision provenance cannot be rebound")
    else:
        session.add(
            BrainSourceRevision(
                company_id=source.company_id,
                source_id=source.source_id,
                source_revision_id=source.source_revision_id,
                revision=source.revision,
                artifact_revision_id=artifact.artifact_revision_id,
                source_event_precision=source.source_event.precision,
                source_event_value=source.source_event.value,
                source_event_basis=source.source_event.basis,
                ingested_at=source.ingested_at,
                recorded_by=source.recorded_by,
                source_author=source.source_author,
                derivation_id=source.derivation_id,
            )
        )
        await session.flush()
