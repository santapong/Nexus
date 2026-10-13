"""Two-hop typed graph lookup with endpoint and complete evidence ACL checks before limits."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, and_, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from nexus.company.brain.access_support import readable_resource_ids
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.models import (
    BrainEntity,
    BrainEntityEvidence,
    BrainEntityRevision,
    BrainEvidence,
    BrainRelationshipEvidence,
    BrainRelationshipRevision,
)
from nexus.company.brain.retrieval import RetrievalLimits
from nexus.company.brain.retrieval_sql import eligible_sources


def visible_entities(scope: BrainReadScope, now: datetime) -> Select[tuple[UUID]]:
    """An entity's grant cannot launder restricted contributing evidence."""
    allowed_evidence = select(BrainEvidence.evidence_id).where(
        BrainEvidence.company_id == scope.company_id,
        BrainEvidence.source_revision_id.in_(eligible_sources(scope, now)),
    )
    hidden = (
        select(literal(1))
        .where(
            BrainEntityEvidence.company_id == scope.company_id,
            BrainEntityEvidence.entity_revision_id == BrainEntity.current_revision_id,
            BrainEntityEvidence.evidence_id.not_in(allowed_evidence),
        )
        .exists()
    )
    return (
        select(BrainEntity.entity_id)
        .join(
            BrainEntityRevision,
            and_(
                BrainEntityRevision.company_id == scope.company_id,
                BrainEntityRevision.entity_revision_id == BrainEntity.current_revision_id,
            ),
        )
        .where(
            BrainEntity.company_id == scope.company_id,
            BrainEntity.resource_id.in_(readable_resource_ids(scope, now)),
            ~hidden,
            or_(
                BrainEntityRevision.validity_start.is_(None),
                BrainEntityRevision.validity_start <= now,
            ),
            or_(BrainEntityRevision.validity_end.is_(None), BrainEntityRevision.validity_end > now),
        )
    )


async def graph_evidence(
    session: AsyncSession,
    scope: BrainReadScope,
    now: datetime,
    ids: tuple[UUID, ...],
    limits: RetrievalLimits,
) -> tuple[dict[UUID, tuple[str, int]], bool]:
    visible = visible_entities(scope, now)
    roots = set((await session.scalars(visible.where(BrainEntity.entity_id.in_(ids)))).all())
    evidence: dict[UUID, tuple[str, int]] = {}
    await _entity_evidence(session, scope, roots, "entity", 0, evidence, limits.max_candidates)
    frontier, seen, edge_count = roots, set(roots), 0
    for hop in range(1, limits.max_hops + 1):
        if not frontier:
            break
        rows = (
            await session.execute(
                _edges(scope, now, frontier, visible).limit(limits.max_edges - edge_count + 1)
            )
        ).all()
        if len(rows) + edge_count > limits.max_edges:
            return evidence, True
        edge_count += len(rows)
        next_ids: set[UUID] = set()
        for _, subject, object_ in rows:
            next_ids.update((subject, object_))
        linked = await session.scalars(
            select(BrainRelationshipEvidence.evidence_id)
            .where(
                BrainRelationshipEvidence.company_id == scope.company_id,
                BrainRelationshipEvidence.relationship_revision_id.in_(
                    tuple(row[0] for row in rows)
                ),
            )
            .order_by(BrainRelationshipEvidence.evidence_id)
            .limit(limits.max_candidates + 1)
        )
        for evidence_id in linked.all():
            evidence.setdefault(evidence_id, ("relationship", hop))
        next_ids -= seen
        await _entity_evidence(
            session, scope, next_ids, "relationship", hop, evidence, limits.max_candidates
        )
        if len(evidence) > limits.max_candidates:
            return evidence, True
        seen |= next_ids
        frontier = next_ids
    return evidence, False


async def _entity_evidence(
    session: AsyncSession,
    scope: BrainReadScope,
    ids: set[UUID],
    kind: str,
    hop: int,
    found: dict[UUID, tuple[str, int]],
    maximum: int,
) -> None:
    if not ids:
        return
    rows = await session.scalars(
        select(BrainEntityEvidence.evidence_id)
        .join(
            BrainEntity,
            and_(
                BrainEntity.company_id == scope.company_id,
                BrainEntity.current_revision_id == BrainEntityEvidence.entity_revision_id,
            ),
        )
        .where(BrainEntityEvidence.company_id == scope.company_id, BrainEntity.entity_id.in_(ids))
        .order_by(BrainEntityEvidence.evidence_id)
        .limit(maximum + 1)
    )
    for evidence_id in rows.all():
        found.setdefault(evidence_id, (kind, hop))


# The 61-line SQL declaration keeps exact endpoints, validity and all contributor
# denial checks in one pre-limit predicate; it performs no Python graph traversal.
def _edges(
    scope: BrainReadScope, now: datetime, frontier: set[UUID], visible: Select[tuple[UUID]]
) -> Select[tuple[UUID, UUID, UUID]]:
    subject, object_ = aliased(BrainEntity), aliased(BrainEntity)
    allowed = select(BrainEvidence.evidence_id).where(
        BrainEvidence.company_id == scope.company_id,
        BrainEvidence.source_revision_id.in_(eligible_sources(scope, now)),
    )
    hidden = (
        select(literal(1))
        .where(
            BrainRelationshipEvidence.company_id == scope.company_id,
            BrainRelationshipEvidence.relationship_revision_id
            == BrainRelationshipRevision.relationship_revision_id,
            BrainRelationshipEvidence.evidence_id.not_in(allowed),
        )
        .exists()
    )
    return (
        select(
            BrainRelationshipRevision.relationship_revision_id,
            BrainRelationshipRevision.subject_id,
            BrainRelationshipRevision.object_id,
        )
        .join(
            subject,
            and_(
                subject.company_id == scope.company_id,
                subject.entity_id == BrainRelationshipRevision.subject_id,
                subject.current_revision_id == BrainRelationshipRevision.subject_revision_id,
            ),
        )
        .join(
            object_,
            and_(
                object_.company_id == scope.company_id,
                object_.entity_id == BrainRelationshipRevision.object_id,
                object_.current_revision_id == BrainRelationshipRevision.object_revision_id,
            ),
        )
        .where(
            BrainRelationshipRevision.company_id == scope.company_id,
            BrainRelationshipRevision.status == "source_report",
            BrainRelationshipRevision.subject_id.in_(visible),
            BrainRelationshipRevision.object_id.in_(visible),
            or_(
                BrainRelationshipRevision.subject_id.in_(frontier),
                BrainRelationshipRevision.object_id.in_(frontier),
            ),
            ~hidden,
            or_(
                BrainRelationshipRevision.validity_start.is_(None),
                BrainRelationshipRevision.validity_start <= now,
            ),
            or_(
                BrainRelationshipRevision.validity_end.is_(None),
                BrainRelationshipRevision.validity_end > now,
            ),
        )
        .order_by(BrainRelationshipRevision.relationship_revision_id)
    )
