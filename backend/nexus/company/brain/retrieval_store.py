"""Bounded native retrieval; opaque metadata precedes rechecked actual-byte publication."""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import BlobReader
from nexus.company.brain.models import (
    BrainEvidence,
    BrainSourceHead,
    BrainSourceRevision,
)
from nexus.company.brain.retrieval import (
    CitationHandle,
    MaterializedEvidence,
    RankedHandle,
    RetrievalLimits,
    RetrievalResult,
    SearchRequest,
)
from nexus.company.brain.retrieval_records import (
    EvidenceBundle,
    bundles,
    contributors,
    heads,
    revision_ref,
)
from nexus.company.brain.retrieval_search import find_candidates
from nexus.company.brain.retrieval_sql import eligible_sources, evidence_ids
from nexus.company.brain.retrieval_support import raw_span_text
from nexus.company.brain.scope_support import (
    BrainConflictError,
    BrainDeniedError,
    brain_transaction,
    revalidate_brain_scope,
)
from nexus.company.brain.sources import SourceHead
from nexus.core.llm.company_registry import DataClassification
from nexus.harness.journal_models import CompanyControl

_KINDS = {"explicit": 0, "entity": 1, "relationship": 2, "fts": 3}
_CLASSIFICATIONS: tuple[DataClassification, ...] = (
    "public",
    "internal",
    "confidential",
    "restricted",
)


# The public reader exceeds 300 lines to keep its shared two-phase
# publication gate explicit; candidate SQL, graph, record and byte helpers are separate modules.
class PersistentBrainRetriever:
    """No cache/vector/reranker/model/network and no caller-controlled storage dependency."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        blobs: BlobReader,
        *,
        limits: RetrievalLimits,
    ) -> None:
        self.factory, self.blobs = factory, blobs
        self.limits = RetrievalLimits.model_validate_json(limits.model_dump_json())

    async def search(
        self, scope: BrainReadScope, identity: VerifiedIdentity, request: SearchRequest
    ) -> RetrievalResult:
        request = SearchRequest.model_validate_json(request.model_dump_json())
        if request.company_id != scope.company_id:
            raise BrainDeniedError("Brain query is unavailable")
        async with brain_transaction(self.factory, scope, identity) as (session, _, now):
            matches, truncated = await find_candidates(session, scope, request, now, self.limits)
            ids = tuple(matches)
            records = await bundles(session, scope, ids) if ids else {}
            ordered = sorted(
                ids,
                key=lambda key: (
                    _KINDS[matches[key][0]],
                    matches[key][1],
                    -matches[key][2],
                    records[key].source.source_id,
                    records[key].revision.source_revision_id,
                    records[key].evidence.chunk_id or key,
                    key,
                ),
            )
            selected = ordered[: self.limits.max_results]
            now = await _clock(session)
            handles = tuple(
                [
                    await self._ranked(session, scope, records[key], matches[key], now)
                    for key in selected
                ]
            )
            for ranked in handles:
                await self._prepare(session, scope, (ranked.handle,), await _clock(session))
            return RetrievalResult(
                company_id=scope.company_id,
                query_sha256=hashlib.sha256(request.model_dump_json().encode()).hexdigest(),
                handles=handles,
                truncated=truncated or len(ordered) > len(selected),
            )

    async def citation_handles(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        ids: tuple[UUID, ...],
        *,
        include_history: bool = True,
    ) -> tuple[CitationHandle, ...]:
        """Exact authorized IDs only; no unrelated FTS hits or new access from caller IDs."""
        if len(ids) > self.limits.max_results or len(set(ids)) != len(ids):
            raise BrainDeniedError("Brain exact selection exceeds its boundary")
        if not ids:
            return ()
        request = SearchRequest(
            company_id=scope.company_id, query="exact evidence", include_history=include_history
        )
        async with brain_transaction(self.factory, scope, identity) as (session, _, now):
            allowed = set(
                (
                    await session.scalars(
                        evidence_ids(scope, now, request).where(BrainEvidence.evidence_id.in_(ids))
                    )
                ).all()
            )
            if allowed != set(ids):
                raise BrainDeniedError("Brain evidence is unavailable")
            records = await bundles(session, scope, ids)
            result = tuple(
                [
                    (
                        await self._ranked(
                            session,
                            scope,
                            records[key],
                            ("explicit", 0, Decimal(0)),
                            await _clock(session),
                        )
                    ).handle
                    for key in ids
                ]
            )
            await self._prepare(session, scope, result, await _clock(session))
            return result

    async def get_evidence(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        ids: tuple[UUID, ...],
        *,
        include_history: bool = True,
    ) -> tuple[MaterializedEvidence, ...]:
        handles = await self.citation_handles(scope, identity, ids, include_history=include_history)
        return await self.materialize(scope, identity, handles)

    async def current_source_heads(
        self, scope: BrainReadScope, identity: VerifiedIdentity, source_ids: tuple[UUID, ...]
    ) -> tuple[SourceHead, ...]:
        if len(source_ids) > 32 or len(set(source_ids)) != len(source_ids):
            raise BrainDeniedError("Brain source selection exceeds its boundary")
        async with brain_transaction(self.factory, scope, identity) as (session, _, now):
            rows = (
                await session.scalars(
                    select(BrainSourceRevision)
                    .join(
                        BrainSourceHead,
                        and_(
                            BrainSourceHead.company_id == scope.company_id,
                            BrainSourceHead.current_revision_id
                            == BrainSourceRevision.source_revision_id,
                        ),
                    )
                    .where(
                        BrainSourceRevision.company_id == scope.company_id,
                        BrainSourceRevision.source_id.in_(source_ids),
                        BrainSourceRevision.source_revision_id.in_(eligible_sources(scope, now)),
                    )
                )
            ).all()
            if len(rows) != len(source_ids):
                raise BrainDeniedError("Brain source state is unavailable")
            refs = tuple(revision_ref(row) for row in rows)
            for row in rows:
                _, resources, _ = await contributors(session, scope, row.source_revision_id)
                await require_resources(session, scope, resources, await _clock(session))
            return await heads(session, scope, refs)

    async def revalidate_handles(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        handles: tuple[CitationHandle, ...],
        now: datetime,
    ) -> None:
        """Trusted final entity/API gate in its existing company-first transaction."""
        if not session.in_transaction() or control.company_id != scope.company_id:
            raise BrainDeniedError("Evidence revalidation requires its company transaction")
        await revalidate_brain_scope(session, control, scope, identity)
        await self._prepare(session, scope, handles, await _clock(session))

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
        from nexus.company.brain.artifact_store import BoundedArtifactReader

        return await BoundedArtifactReader(self.factory, self.blobs).bounded_artifact(
            scope,
            identity,
            artifact_revision_id,
            start_byte=start_byte,
            max_bytes=max_bytes,
            include_history=include_history,
        )

    async def _ranked(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        bundle: EvidenceBundle,
        match: tuple[str, int, Decimal],
        now: datetime,
    ) -> RankedHandle:
        refs, resource_ids, _ = await contributors(
            session, scope, bundle.revision.source_revision_id
        )
        handle = CitationHandle(
            company_id=scope.company_id,
            evidence_id=bundle.evidence.evidence_id,
            record=bundle.record(),
            source_contributors=refs,
            source_heads=await heads(session, scope, refs),
            contributors=await require_resources(session, scope, resource_ids, now),
        )
        return RankedHandle.model_validate(
            {
                "company_id": scope.company_id,
                "handle": handle,
                "match_kind": match[0],
                "hop": match[1],
                "rank": match[2],
            }
        )

    async def materialize(
        self, scope: BrainReadScope, identity: VerifiedIdentity, handles: tuple[CitationHandle, ...]
    ) -> tuple[MaterializedEvidence, ...]:
        handles = tuple(
            CitationHandle.model_validate_json(item.model_dump_json()) for item in handles
        )
        if (
            len(handles) > self.limits.max_results
            or len({item.evidence_id for item in handles}) != len(handles)
            or any(item.company_id != scope.company_id for item in handles)
        ):
            raise BrainDeniedError("Brain materialization selection exceeds its boundary")
        if not handles:
            return ()
        async with brain_transaction(self.factory, scope, identity) as (session, _, now):
            prepared = await self._prepare(session, scope, handles, now)
        raw = {
            key: await self.blobs.read(bundle.record().artifact) for key, bundle in prepared.items()
        }
        texts = {
            key: raw_span_text(bundle.record(), bundle.artifact_record(), raw[key])
            for key, bundle in prepared.items()
        }
        async with brain_transaction(self.factory, scope, identity) as (session, _, _):
            current = await self._prepare(session, scope, handles, await _clock(session))
            result = tuple(
                [
                    await self._material(
                        session, scope, current[item.evidence_id], item, texts[item.evidence_id]
                    )
                    for item in handles
                ]
            )
            # Expiry may advance during row/hash work even while the company lock is held.
            await self._prepare(session, scope, handles, await _clock(session))
            return result

    async def _prepare(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        handles: tuple[CitationHandle, ...],
        now: datetime,
    ) -> dict[UUID, EvidenceBundle]:
        ids = tuple(item.evidence_id for item in handles)
        allowed = set(
            (
                await session.scalars(
                    select(BrainEvidence.evidence_id).where(
                        BrainEvidence.company_id == scope.company_id,
                        BrainEvidence.evidence_id.in_(ids),
                        BrainEvidence.source_revision_id.in_(eligible_sources(scope, now)),
                    )
                )
            ).all()
        )
        if allowed != set(ids):
            raise BrainDeniedError("Brain evidence is unavailable")
        records = await bundles(session, scope, ids)
        for item in handles:
            bundle = records[item.evidence_id]
            if item.record != bundle.record():
                raise BrainConflictError("Brain exact citation changed or was spliced")
            refs, resources, _ = await contributors(
                session, scope, bundle.revision.source_revision_id
            )
            grants = await require_resources(session, scope, resources, now)
            if refs != item.source_contributors or grants != item.contributors:
                raise BrainConflictError("Brain contributor access changed; search again")
            if await heads(session, scope, refs) != item.source_heads:
                raise BrainConflictError("Brain source heads changed; search again")
        return records

    async def _material(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        bundle: EvidenceBundle,
        handle: CitationHandle,
        text: str,
    ) -> MaterializedEvidence:
        refs, _, sources = await contributors(session, scope, bundle.revision.source_revision_id)
        current = await heads(session, scope, refs)
        known = {row.source_id: row for row in current}
        historical = any(known[ref.source_id].current != ref for ref in refs)
        now = await _clock(session)
        freshness = (
            "stale"
            if any(
                row.availability != "available"
                or (row.fresh_until is not None and row.fresh_until <= now)
                for row in current
            )
            else "unknown"
            if any(row.fresh_until is None for row in current)
            else "fresh"
        )
        classification = max(
            (row.data_classification for row in sources), key=_CLASSIFICATIONS.index
        )
        return MaterializedEvidence.model_validate(
            {
                "company_id": scope.company_id,
                "record": bundle.record(),
                "text": text,
                "source_state": "historical" if historical else "current",
                "freshness": freshness,
                "data_classification": classification,
                "authority_profile": bundle.source.authority_profile,
                "source_symbol": bundle.source.source_symbol,
                "external_key": bundle.source.external_key,
                "contributors": handle.contributors,
                "source_contributors": refs,
            }
        )


async def _clock(session: AsyncSession) -> datetime:
    now: datetime | None = await session.scalar(select(func.clock_timestamp()))
    if now is None or now.utcoffset() is None:
        raise BrainDeniedError("Brain clock is unavailable")
    return now
