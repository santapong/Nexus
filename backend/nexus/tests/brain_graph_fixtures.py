"""Typed source-backed graph fixture setup; no execution completion or authority publication."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
from nexus.company.brain.base import SourceTime
from nexus.company.brain.models import (
    BrainEntity,
    BrainEntityEvidence,
    BrainEntityRevision,
    BrainRelationshipEvidence,
    BrainRelationshipRevision,
)
from nexus.company.brain.ontology import (
    CompanyContent,
    DepartmentContent,
    EntityRevisionRecord,
    GoalContent,
)
from nexus.company.brain.relationships import RelationshipRecord
from nexus.company.brain.sources import EvidenceRef
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER

ROOT, DEPARTMENT, GOAL = (UUID(int=value) for value in (2100, 2101, 2102))
DEPT_RESOURCE = UUID(int=2103)


async def _graph_fixture(factory: async_sessionmaker[AsyncSession], ids: tuple[UUID, ...]) -> None:
    records = (
        _entity(ROOT, CompanyContent(label="Company graph root"), RESOURCE),
        _entity(DEPARTMENT, DepartmentContent(label="Private department"), DEPT_RESOURCE),
        _entity(GOAL, GoalContent(label="Goal reached at two hops"), RESOURCE, ids[2]),
    )
    relations = (
        RelationshipRecord(
            company_id=COMPANY,
            relationship_id=UUID(int=2200),
            relationship_revision_id=UUID(int=2201),
            revision="1",
            predicate="has_department",
            subject=records[0],
            object=records[1],
            evidence=(EvidenceRef(company_id=COMPANY, evidence_id=ids[0]),),
            origin="source",
            status="source_report",
            recorded_at=records[0].ingested_at,
        ),
        RelationshipRecord(
            company_id=COMPANY,
            relationship_id=UUID(int=2202),
            relationship_revision_id=UUID(int=2203),
            revision="1",
            predicate="owns_goal",
            subject=records[1],
            object=records[2],
            evidence=(EvidenceRef(company_id=COMPANY, evidence_id=ids[1]),),
            origin="source",
            status="source_report",
            recorded_at=records[0].ingested_at,
        ),
    )
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        await _endpoint_grant(session)
        for record in records:
            await _persist_entity(session, record)
        for relation in relations:
            await _persist_relationship(session, relation)


async def _endpoint_grant(session: AsyncSession) -> None:
    session.add(BrainResource(company_id=COMPANY, resource_id=DEPT_RESOURCE, kind="entity"))
    await session.flush()
    for principal in (ACTOR, OWNER):
        session.add(
            BrainResourceAccess(
                company_id=COMPANY,
                resource_id=DEPT_RESOURCE,
                principal_id=principal,
                active=True,
                generation=1,
            )
        )
    await session.flush()


def _entity(
    key: UUID,
    content: CompanyContent | DepartmentContent | GoalContent,
    resource_id: UUID,
    evidence: UUID | None = None,
) -> EntityRevisionRecord:
    from datetime import UTC, datetime

    return EntityRevisionRecord(
        company_id=COMPANY,
        entity_id=key,
        entity_revision_id=UUID(int=key.int + 100),
        revision="1",
        kind=content.kind,
        resource=ResourceRef(company_id=COMPANY, resource_id=resource_id),
        content=content,
        evidence=(EvidenceRef(company_id=COMPANY, evidence_id=evidence),) if evidence else (),
        source_event=SourceTime(
            precision="unknown", value=None, basis="typed synthetic graph fixture"
        ),
        ingested_at=datetime.now(UTC),
        origin="source",
        status="source_report",
    )


async def _persist_entity(session: AsyncSession, record: EntityRevisionRecord) -> None:
    row = BrainEntity(
        company_id=record.company_id,
        entity_id=record.entity_id,
        resource_id=record.resource.resource_id,
        kind=record.kind,
    )
    session.add(row)
    await session.flush()
    session.add(
        BrainEntityRevision(
            company_id=record.company_id,
            entity_revision_id=record.entity_revision_id,
            entity_id=record.entity_id,
            kind=record.kind,
            revision=record.revision,
            content_json=record.content.model_dump_json(),
            source_event_json=record.source_event.model_dump_json(),
            ingested_at=record.ingested_at,
            origin=record.origin,
            status=record.status,
        )
    )
    await session.flush()
    row.current_revision_id = record.entity_revision_id
    for citation in record.evidence:
        session.add(
            BrainEntityEvidence(
                company_id=record.company_id,
                entity_revision_id=record.entity_revision_id,
                evidence_id=citation.evidence_id,
            )
        )
    await session.flush()


async def _persist_relationship(session: AsyncSession, record: RelationshipRecord) -> None:
    session.add(
        BrainRelationshipRevision(
            company_id=record.company_id,
            relationship_id=record.relationship_id,
            relationship_revision_id=record.relationship_revision_id,
            revision=record.revision,
            predicate=record.predicate,
            subject_id=record.subject.entity_id,
            subject_revision_id=record.subject.entity_revision_id,
            subject_kind=record.subject.kind,
            object_id=record.object.entity_id,
            object_revision_id=record.object.entity_revision_id,
            object_kind=record.object.kind,
            origin=record.origin,
            status=record.status,
        )
    )
    await session.flush()
    for citation in record.evidence:
        session.add(
            BrainRelationshipEvidence(
                company_id=record.company_id,
                relationship_revision_id=record.relationship_revision_id,
                evidence_id=citation.evidence_id,
            )
        )
    await session.flush()
