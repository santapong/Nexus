"""Resolve native rows to exact immutable source citations and contributor snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import BrainReadScope, SourceTime
from nexus.company.brain.models import (
    BrainArtifactRevision,
    BrainDerivation,
    BrainEvidence,
    BrainSource,
    BrainSourceHead,
    BrainSourceRevision,
)
from nexus.company.brain.retrieval_sql import source_closure
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.sources import (
    ArtifactRevisionRecord,
    ArtifactRevisionRef,
    EvidenceRecord,
    SourceHead,
    SourceRevisionRef,
    UTF8Span,
)


@dataclass(frozen=True)
class EvidenceBundle:
    source: BrainSource
    revision: BrainSourceRevision
    artifact: BrainArtifactRevision
    evidence: BrainEvidence
    head: BrainSourceHead

    def artifact_record(self) -> ArtifactRevisionRecord:
        row = self.artifact
        return ArtifactRevisionRecord.model_validate(
            {
                "company_id": row.company_id,
                "artifact_id": row.artifact_id,
                "artifact_revision_id": row.artifact_revision_id,
                "revision": row.revision,
                "resource": ResourceRef(company_id=row.company_id, resource_id=row.resource_id),
                "media_type": row.media_type,
                "storage_symbol": row.storage_symbol,
                "raw_text": row.raw_text,
                "sha256": row.sha256,
                "byte_length": row.byte_length,
                "recorded_at": row.recorded_at,
                "derivation_id": row.derivation_id,
            }
        )

    def record(self) -> EvidenceRecord:
        row, revision = self.evidence, self.revision
        artifact = self.artifact_record()
        raw = UTF8Span(
            start_byte=row.raw_start_byte,
            end_byte=row.raw_end_byte,
            section=row.raw_section,
            path=row.raw_path,
            page=row.raw_page,
        )
        parsed = (
            UTF8Span(start_byte=row.parsed_start_byte, end_byte=row.parsed_end_byte)
            if row.parsed_start_byte is not None and row.parsed_end_byte is not None
            else None
        )
        return EvidenceRecord(
            company_id=row.company_id,
            evidence_id=row.evidence_id,
            source=revision_ref(revision),
            artifact=ArtifactRevisionRef(
                company_id=artifact.company_id,
                artifact_id=artifact.artifact_id,
                artifact_revision_id=artifact.artifact_revision_id,
                revision=artifact.revision,
                sha256=artifact.sha256,
                byte_length=artifact.byte_length,
            ),
            raw_span=raw,
            span_sha256=row.span_sha256,
            source_event=SourceTime.model_validate(
                {
                    "precision": revision.source_event_precision,
                    "value": revision.source_event_value,
                    "basis": revision.source_event_basis,
                }
            ),
            ingested_at=revision.ingested_at,
            parse_revision_id=row.parse_revision_id,
            parsed_span=parsed,
            chunk_id=row.chunk_id,
        )


def revision_ref(row: BrainSourceRevision) -> SourceRevisionRef:
    return SourceRevisionRef(
        company_id=row.company_id,
        source_id=row.source_id,
        source_revision_id=row.source_revision_id,
        revision=row.revision,
    )


# The complete exact source/evidence/artifact join stays together beyond 50 lines
# so its company-bound FK mapping remains reviewable beside the projected records.
async def bundles(
    session: AsyncSession, scope: BrainReadScope, ids: tuple[UUID, ...]
) -> dict[UUID, EvidenceBundle]:
    rows = (
        await session.execute(
            select(
                BrainSource,
                BrainSourceRevision,
                BrainArtifactRevision,
                BrainEvidence,
                BrainSourceHead,
            )
            .select_from(BrainEvidence)
            .join(
                BrainSourceRevision,
                and_(
                    BrainSourceRevision.company_id == scope.company_id,
                    BrainSourceRevision.source_revision_id == BrainEvidence.source_revision_id,
                ),
            )
            .join(
                BrainSource,
                and_(
                    BrainSource.company_id == scope.company_id,
                    BrainSource.source_id == BrainSourceRevision.source_id,
                ),
            )
            .join(
                BrainArtifactRevision,
                and_(
                    BrainArtifactRevision.company_id == scope.company_id,
                    BrainArtifactRevision.artifact_revision_id
                    == BrainEvidence.artifact_revision_id,
                ),
            )
            .join(
                BrainSourceHead,
                and_(
                    BrainSourceHead.company_id == scope.company_id,
                    BrainSourceHead.source_id == BrainSource.source_id,
                ),
            )
            .where(BrainEvidence.company_id == scope.company_id, BrainEvidence.evidence_id.in_(ids))
        )
    ).all()
    result = {
        evidence.evidence_id: EvidenceBundle(source, revision, artifact, evidence, head)
        for source, revision, artifact, evidence, head in rows
    }
    if set(result) != set(ids):
        raise BrainDeniedError("Brain evidence is unavailable")
    return result


# This bounded closure collector exceeds 50 lines to show every required resource
# beside its immutable source reference; rank/snippet publication remains in the store.
async def contributors(
    session: AsyncSession, scope: BrainReadScope, root: UUID
) -> tuple[tuple[SourceRevisionRef, ...], tuple[UUID, ...], tuple[BrainSource, ...]]:
    closure = source_closure(scope.company_id)
    rows = (
        await session.execute(
            select(BrainSourceRevision, BrainSource, BrainArtifactRevision)
            .join(
                BrainSource,
                and_(
                    BrainSource.company_id == scope.company_id,
                    BrainSource.source_id == BrainSourceRevision.source_id,
                ),
            )
            .join(
                BrainArtifactRevision,
                and_(
                    BrainArtifactRevision.company_id == scope.company_id,
                    BrainArtifactRevision.artifact_revision_id
                    == BrainSourceRevision.artifact_revision_id,
                ),
            )
            .where(
                BrainSourceRevision.company_id == scope.company_id,
                BrainSourceRevision.source_revision_id.in_(
                    select(closure.c.node).where(closure.c.root == root)
                ),
            )
            .order_by(BrainSourceRevision.source_revision_id)
        )
    ).all()
    if not rows or len(rows) > 32:
        raise BrainDeniedError("Brain provenance exceeds its boundary")
    resources = {
        value
        for _, source, artifact in rows
        for value in (source.resource_id, artifact.resource_id)
    }
    derivation_ids = {
        value
        for revision, _, artifact in rows
        for value in (revision.derivation_id, artifact.derivation_id)
        if value is not None
    }
    if derivation_ids:
        extra = await session.scalars(
            select(BrainArtifactRevision.resource_id)
            .join(
                BrainDerivation,
                and_(
                    BrainDerivation.company_id == scope.company_id,
                    BrainDerivation.artifact_revision_id
                    == BrainArtifactRevision.artifact_revision_id,
                ),
            )
            .where(
                BrainArtifactRevision.company_id == scope.company_id,
                BrainDerivation.derivation_id.in_(derivation_ids),
            )
        )
        resources.update(extra.all())
    if len(resources) > 32:
        raise BrainDeniedError("Brain provenance exceeds its resource boundary")
    return (
        tuple(revision_ref(row) for row, _, _ in rows),
        tuple(sorted(resources)),
        tuple(source for _, source, _ in rows),
    )


async def heads(
    session: AsyncSession, scope: BrainReadScope, refs: tuple[SourceRevisionRef, ...]
) -> tuple[SourceHead, ...]:
    ids = {ref.source_id for ref in refs}
    rows = (
        await session.execute(
            select(BrainSourceHead, BrainSourceRevision)
            .join(
                BrainSourceRevision,
                and_(
                    BrainSourceRevision.company_id == scope.company_id,
                    BrainSourceRevision.source_revision_id == BrainSourceHead.current_revision_id,
                ),
            )
            .where(
                BrainSourceHead.company_id == scope.company_id, BrainSourceHead.source_id.in_(ids)
            )
            .order_by(BrainSourceHead.source_id)
        )
    ).all()
    if len(rows) != len(ids):
        raise BrainDeniedError("Brain current source state is unavailable")
    return tuple(
        SourceHead.model_validate(
            {
                "company_id": scope.company_id,
                "source_id": row.source_id,
                "current": revision_ref(revision),
                "generation": row.generation,
                "observed_at": row.observed_at,
                "fresh_until": row.fresh_until,
                "availability": row.availability,
            }
        )
        for row, revision in rows
    )
