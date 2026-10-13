"""Actual bounded raw artifact bytes through two-phase current contributor access checks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.access_support import readable_resource_ids, require_resources
from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import BlobReader
from nexus.company.brain.models import (
    BrainArtifactRevision,
    BrainDerivationEvidence,
    BrainDerivationSource,
    BrainEvidence,
    BrainSourceRevision,
)
from nexus.company.brain.retrieval_records import contributors, heads
from nexus.company.brain.retrieval_sql import eligible_sources
from nexus.company.brain.retrieval_store import _clock
from nexus.company.brain.scope_support import (
    BrainConflictError,
    BrainDeniedError,
    brain_transaction,
)
from nexus.company.brain.sources import ArtifactRevisionRef, SourceHead, SourceRevisionRef, UTF8Span


@dataclass(frozen=True)
class _Snapshot:
    artifact: ArtifactRevisionRef
    raw_text: str
    refs: tuple[SourceRevisionRef, ...]
    grants: tuple[ResourceGeneration, ...]
    heads: tuple[SourceHead, ...]
    classification: str
    historical: bool


class BoundedArtifactReader:
    def __init__(self, factory: async_sessionmaker[AsyncSession], blobs: BlobReader) -> None:
        self.factory, self.blobs = factory, blobs

    # The 51-line two-phase gate keeps its final snapshot comparison adjacent to
    # the returned slice; protected byte validation is isolated outside the lock.
    async def bounded_artifact(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        artifact_revision_id: UUID,
        *,
        start_byte: int,
        max_bytes: int,
        include_history: bool,
    ) -> ArtifactSlice:
        if (
            type(start_byte) is not int
            or start_byte < 0
            or type(max_bytes) is not int
            or not 0 < max_bytes <= 16384
            or type(include_history) is not bool
        ):
            raise BrainDeniedError("Artifact byte request exceeds its boundary")
        async with brain_transaction(self.factory, scope, identity) as (session, _, now):
            first = await self._snapshot(session, scope, artifact_revision_id, now, include_history)
        raw = await self.blobs.read(first.artifact)
        end, text = _checked_slice(first, raw, start_byte, max_bytes)
        async with brain_transaction(self.factory, scope, identity) as (session, _, _):
            current = await self._snapshot(
                session, scope, artifact_revision_id, await _clock(session), include_history
            )
            if current != first:
                raise BrainConflictError("Artifact current source/access changed; reload")
            result = ArtifactSlice.model_validate(
                {
                    "company_id": scope.company_id,
                    "artifact": current.artifact,
                    "span": UTF8Span(start_byte=start_byte, end_byte=end),
                    "span_sha256": hashlib.sha256(raw[start_byte:end]).hexdigest(),
                    "text": text,
                    "source_contributors": current.refs,
                    "contributors": current.grants,
                    "source_heads": current.heads,
                    "data_classification": current.classification,
                    "source_state": "historical" if current.historical else "current",
                    "has_more": end < len(raw),
                }
            )
            if (
                await self._snapshot(
                    session, scope, artifact_revision_id, await _clock(session), include_history
                )
                != current
            ):
                raise BrainConflictError("Artifact current state changed during materialization")
            return result

    # The bounded contributor snapshot exceeds 50 lines to keep every direct/derived
    # grant, head and historical comparison beside the classification it justifies.
    async def _snapshot(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        key: UUID,
        now: datetime,
        include_history: bool,
    ) -> _Snapshot:
        row = await session.scalar(
            select(BrainArtifactRevision).where(
                BrainArtifactRevision.company_id == scope.company_id,
                BrainArtifactRevision.artifact_revision_id == key,
                BrainArtifactRevision.resource_id.in_(readable_resource_ids(scope, now)),
            )
        )
        if row is None:
            raise BrainDeniedError("Artifact is unavailable")
        roots = await _artifact_roots(session, scope, row)
        if not roots or len(roots) > 32:
            raise BrainDeniedError("Artifact provenance is unavailable")
        allowed = set(
            (
                await session.scalars(
                    eligible_sources(scope, now).where(
                        BrainSourceRevision.source_revision_id.in_(roots)
                    )
                )
            ).all()
        )
        if allowed != roots:
            raise BrainDeniedError("Artifact contributing provenance is unavailable")
        all_refs: dict[UUID, SourceRevisionRef] = {}
        resources = {row.resource_id}
        classes: list[str] = []
        for root in sorted(roots):
            refs, required, sources = await contributors(session, scope, root)
            all_refs.update({ref.source_revision_id: ref for ref in refs})
            resources.update(required)
            classes.extend(source.data_classification for source in sources)
        refs = tuple(all_refs[key] for key in sorted(all_refs))
        current = await heads(session, scope, refs)
        pointer = {head.source_id: head.current for head in current}
        historical = any(pointer[ref.source_id] != ref for ref in refs)
        if historical and not include_history:
            raise BrainConflictError("Artifact is historical; explicitly request history")
        grants = await require_resources(
            session, scope, tuple(sorted(resources)), await _clock(session)
        )
        artifact = ArtifactRevisionRef(
            company_id=row.company_id,
            artifact_id=row.artifact_id,
            artifact_revision_id=row.artifact_revision_id,
            revision=row.revision,
            sha256=row.sha256,
            byte_length=row.byte_length,
        )
        return _Snapshot(
            artifact,
            row.raw_text,
            refs,
            grants,
            current,
            max(classes, key=("public", "internal", "confidential", "restricted").index),
            historical,
        )


def _checked_slice(
    snapshot: _Snapshot, raw: bytes, start_byte: int, max_bytes: int
) -> tuple[int, str]:
    """Check the full protected blob before decoding the exact requested byte slice."""
    if (
        raw != snapshot.raw_text.encode()
        or hashlib.sha256(raw).hexdigest() != snapshot.artifact.sha256
        or len(raw) != snapshot.artifact.byte_length
        or start_byte >= len(raw)
    ):
        raise BrainDeniedError("Artifact bytes are unavailable")
    end = min(len(raw), start_byte + max_bytes)
    try:
        return end, raw[start_byte:end].decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise BrainDeniedError("Artifact byte boundary splits UTF8 content") from exc


async def _artifact_roots(
    session: AsyncSession, scope: BrainReadScope, artifact: BrainArtifactRevision
) -> set[UUID]:
    """Collect exact direct and derivation roots; this does not grant access."""
    roots = set(
        (
            await session.scalars(
                select(BrainSourceRevision.source_revision_id).where(
                    BrainSourceRevision.company_id == scope.company_id,
                    BrainSourceRevision.artifact_revision_id == artifact.artifact_revision_id,
                )
            )
        ).all()
    )
    if artifact.derivation_id is not None:
        roots.update(
            (
                await session.scalars(
                    select(BrainDerivationSource.source_revision_id).where(
                        BrainDerivationSource.company_id == scope.company_id,
                        BrainDerivationSource.derivation_id == artifact.derivation_id,
                    )
                )
            ).all()
        )
        roots.update(
            (
                await session.scalars(
                    select(BrainEvidence.source_revision_id)
                    .join(
                        BrainDerivationEvidence,
                        and_(
                            BrainDerivationEvidence.company_id == scope.company_id,
                            BrainDerivationEvidence.evidence_id == BrainEvidence.evidence_id,
                        ),
                    )
                    .where(
                        BrainEvidence.company_id == scope.company_id,
                        BrainDerivationEvidence.derivation_id == artifact.derivation_id,
                    )
                )
            ).all()
        )
    return roots
