"""Immutable exact claim projections and owner-only evidence-bound acyclic links."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import BrainReadScope, SourceTime, ValidityInterval
from nexus.company.brain.claim_models import (
    BrainClaimEvidence,
    BrainClaimLink,
    BrainClaimLinkEvidence,
    BrainClaimRevision,
)
from nexus.company.brain.claims import ClaimLink, ClaimRecord, ClaimRevisionRef
from nexus.company.brain.event_store import append_event
from nexus.company.brain.publication_contracts import ClaimLinkPublication
from nexus.company.brain.publication_evidence import prepare_evidence, recheck_publication
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import (
    BrainConflictError,
    BrainDeniedError,
    brain_transaction,
)
from nexus.company.brain.sources import EvidenceRef


async def claim_record(session: AsyncSession, row: BrainClaimRevision) -> ClaimRecord:
    edges = (
        await session.execute(
            select(BrainClaimEvidence.evidence_id, BrainClaimEvidence.relationship)
            .where(
                BrainClaimEvidence.company_id == row.company_id,
                BrainClaimEvidence.claim_revision_id == row.claim_revision_id,
            )
            .order_by(BrainClaimEvidence.evidence_id)
        )
    ).all()
    return ClaimRecord.model_validate(
        {
            "company_id": row.company_id,
            "claim_id": row.claim_id,
            "claim_revision_id": row.claim_revision_id,
            "revision": row.revision,
            "resource": ResourceRef(company_id=row.company_id, resource_id=row.resource_id),
            "kind": row.kind,
            "text": row.text,
            "supporting": tuple(
                EvidenceRef(company_id=row.company_id, evidence_id=key)
                for key, relationship in edges
                if relationship == "supports"
            ),
            "challenging": tuple(
                EvidenceRef(company_id=row.company_id, evidence_id=key)
                for key, relationship in edges
                if relationship == "challenges"
            ),
            "source_event": SourceTime.model_validate_json(row.source_event_json),
            "ingested_at": row.ingested_at,
            "validity": ValidityInterval(start=row.validity_start, end=row.validity_end),
            "origin": row.origin,
            "status": row.status,
            "verification_id": row.verification_id,
            "receipt_id": row.receipt_id,
        }
    )


async def exact_claim(
    session: AsyncSession, scope: BrainReadScope, ref: ClaimRevisionRef
) -> ClaimRecord:
    row = await session.get(BrainClaimRevision, (scope.company_id, ref.claim_revision_id))
    if (
        ref.company_id != scope.company_id
        or row is None
        or (row.claim_id, row.revision) != (ref.claim_id, ref.revision)
    ):
        raise BrainDeniedError("Exact linked claim revision is unavailable")
    return await claim_record(session, row)


async def _acyclic(session: AsyncSession, command: ClaimLinkPublication) -> None:
    frontier = {command.object.claim_revision_id}
    target = command.subject.claim_revision_id
    seen = set(frontier)
    for _ in range(16):
        if not frontier:
            return
        children = tuple(
            (
                await session.scalars(
                    select(BrainClaimLink.object_revision_id)
                    .where(
                        BrainClaimLink.company_id == command.company_id,
                        BrainClaimLink.subject_revision_id.in_(frontier),
                        BrainClaimLink.predicate == "supersedes",
                    )
                    .limit(33)
                )
            ).all()
        )
        if target in children:
            raise BrainConflictError("Claim supersession would create a cycle")
        if len(children) > 32:
            raise BrainDeniedError("Claim supersession exceeds its bounded graph")
        frontier = set(children) - seen
        seen.update(frontier)
        if len(seen) > 32:
            raise BrainDeniedError("Claim supersession exceeds its bounded graph")
    if frontier:
        raise BrainDeniedError("Claim supersession exceeds its bounded depth")


async def _link_record(
    session: AsyncSession, row: BrainClaimLink, subject: ClaimRecord, object_: ClaimRecord
) -> ClaimLink:
    if (row.subject_revision_id, row.object_revision_id) != (
        subject.claim_revision_id,
        object_.claim_revision_id,
    ):
        raise BrainConflictError("Stored claim link endpoints cannot be rebound")
    keys = tuple(
        (
            await session.scalars(
                select(BrainClaimLinkEvidence.evidence_id)
                .where(
                    BrainClaimLinkEvidence.company_id == row.company_id,
                    BrainClaimLinkEvidence.link_id == row.link_id,
                )
                .order_by(BrainClaimLinkEvidence.evidence_id)
            )
        ).all()
    )
    return ClaimLink.model_validate(
        {
            "company_id": row.company_id,
            "link_id": row.link_id,
            "subject": ClaimRevisionRef.model_validate_json(
                subject.model_dump_json(include=set(ClaimRevisionRef.model_fields))
            ),
            "object": ClaimRevisionRef.model_validate_json(
                object_.model_dump_json(include=set(ClaimRevisionRef.model_fields))
            ),
            "predicate": row.predicate,
            "rationale": row.rationale,
            "evidence": tuple(
                EvidenceRef(company_id=row.company_id, evidence_id=key) for key in keys
            ),
            "recorded_by": row.recorded_by,
            "recorded_at": row.recorded_at,
        }
    )


async def publish_link(
    factory: async_sessionmaker[AsyncSession],
    retriever: PersistentBrainRetriever,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    command: ClaimLinkPublication,
) -> ClaimLink:
    command = ClaimLinkPublication.model_validate_json(command.model_dump_json())
    if command.company_id != scope.company_id:
        raise BrainDeniedError("Claim link is unavailable")
    async with brain_transaction(factory, scope, identity, owner=True) as (session, _, _):
        subject, object_ = (
            await exact_claim(session, scope, command.subject),
            await exact_claim(session, scope, command.object),
        )
    references = tuple(
        sorted(
            set(
                command.evidence
                + subject.supporting
                + subject.challenging
                + object_.supporting
                + object_.challenging
            ),
            key=lambda ref: ref.evidence_id,
        )
    )
    prepared = await prepare_evidence(retriever, scope, identity, references)
    async with brain_transaction(factory, scope, identity, owner=True) as (session, control, _):
        current_subject, current_object = (
            await exact_claim(session, scope, command.subject),
            await exact_claim(session, scope, command.object),
        )
        if (current_subject, current_object) != (subject, object_):
            raise BrainConflictError("Claim link references changed")
        resources = tuple(sorted({subject.resource.resource_id, object_.resource.resource_id}))
        now = await recheck_publication(
            retriever, session, control, scope, identity, prepared, resources, model=False
        )
        result = ClaimLink.model_validate(
            command.model_dump()
            | {
                "recorded_by": scope.principal_id,
                "recorded_at": now,
            }
        )
        existing = await session.get(BrainClaimLink, (scope.company_id, command.link_id))
        if existing is not None:
            prior = await _link_record(session, existing, subject, object_)
            if prior.model_dump(exclude={"recorded_at"}) != result.model_dump(
                exclude={"recorded_at"}
            ):
                raise BrainConflictError("Claim link identity cannot be rebound")
            return prior
        if command.predicate == "supersedes":
            await _acyclic(session, command)
        await _save_link(session, result)
        for resource_id in resources:
            await append_event(
                session,
                scope,
                kind="claims_changed",
                resource_id=resource_id,
                deduplication_key=f"claim-link:{command.link_id}:{resource_id}",
                now=now,
            )
        await recheck_publication(
            retriever, session, control, scope, identity, prepared, resources, model=False
        )
        return result


async def _save_link(session: AsyncSession, value: ClaimLink) -> None:
    session.add(
        BrainClaimLink(
            company_id=value.company_id,
            link_id=value.link_id,
            subject_revision_id=value.subject.claim_revision_id,
            object_revision_id=value.object.claim_revision_id,
            predicate=value.predicate,
            rationale=value.rationale,
            recorded_by=value.recorded_by,
            recorded_at=value.recorded_at,
        )
    )
    await session.flush()
    for ref in value.evidence:
        session.add(
            BrainClaimLinkEvidence(
                company_id=value.company_id, link_id=value.link_id, evidence_id=ref.evidence_id
            )
        )
    await session.flush()
