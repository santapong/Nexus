"""Permission-filtered exact/graph/FTS candidate selection, separate from publication."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Float, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.models import BrainChunk, BrainEvidence
from nexus.company.brain.retrieval import RetrievalLimits, SearchRequest
from nexus.company.brain.retrieval_graph import graph_evidence
from nexus.company.brain.retrieval_sql import evidence_ids
from nexus.company.brain.scope_support import BrainDeniedError


async def find_candidates(
    session: AsyncSession,
    scope: BrainReadScope,
    request: SearchRequest,
    now: datetime,
    limits: RetrievalLimits,
) -> tuple[dict[UUID, tuple[str, int, Decimal]], bool]:
    allowed = evidence_ids(scope, now, request)
    found: dict[UUID, tuple[str, int, Decimal]] = {}
    if request.explicit_evidence_ids:
        explicit = await session.scalars(
            allowed.where(BrainEvidence.evidence_id.in_(request.explicit_evidence_ids))
        )
        found.update({key: ("explicit", 0, Decimal(0)) for key in explicit.all()})
    truncated = False
    if request.entity_ids:
        graph, truncated = await graph_evidence(session, scope, now, request.entity_ids, limits)
        valid = await session.scalars(allowed.where(BrainEvidence.evidence_id.in_(tuple(graph))))
        found.update({key: (*graph[key], Decimal(0)) for key in valid.all() if key not in found})
    # The initial recipe does not claim Thai tokenization/semantic search.
    if any("\u0e00" <= char <= "\u0e7f" for char in request.query):
        if not request.explicit_evidence_ids and not request.entity_ids:
            raise BrainDeniedError("Search language is unqualified; select explicit evidence")
    else:
        fts, fts_truncated = await _fts_candidates(session, scope, request, now, limits)
        truncated |= fts_truncated
        for key, rank in fts.items():
            found.setdefault(key, ("fts", 0, rank))
    truncated |= len(found) > limits.max_candidates
    priority = {"explicit": 0, "entity": 1, "relationship": 2, "fts": 3}
    keys = sorted(
        found, key=lambda key: (priority[found[key][0]], found[key][1], -found[key][2], key)
    )[: limits.max_candidates]
    return {key: found[key] for key in keys}, truncated


async def _fts_candidates(
    session: AsyncSession,
    scope: BrainReadScope,
    request: SearchRequest,
    now: datetime,
    limits: RetrievalLimits,
) -> tuple[dict[UUID, Decimal], bool]:
    query = func.websearch_to_tsquery("simple", request.query)
    rank = func.ts_rank_cd(BrainChunk.search_vector, query, type_=Float)
    statement = (
        select(BrainEvidence.evidence_id, rank)
        .join(
            BrainChunk,
            and_(
                BrainChunk.company_id == scope.company_id,
                BrainChunk.chunk_id == BrainEvidence.chunk_id,
            ),
        )
        .where(
            BrainEvidence.company_id == scope.company_id,
            BrainEvidence.evidence_id.in_(evidence_ids(scope, now, request)),
            BrainChunk.search_config == "simple",
            BrainChunk.search_vector.bool_op("@@")(query),
        )
        .order_by(rank.desc(), BrainEvidence.evidence_id)
        .limit(limits.max_candidates + 1)
    )
    rows = (await session.execute(statement)).all()
    return (
        {key: Decimal(str(value)) for key, value in rows[: limits.max_candidates]},
        len(rows) > limits.max_candidates,
    )
