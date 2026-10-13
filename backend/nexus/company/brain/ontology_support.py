"""Exact native reference resolution and typed immutable ontology projections."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid5

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import BrainReadScope, SourceTime, ValidityInterval
from nexus.company.brain.ontology import (
    ActionContent,
    ArtifactContent,
    EntityContent,
    EntityRevisionRecord,
    EntityRevisionRef,
    EvidenceContent,
    PrincipalContent,
    VerificationContent,
    WorkItemContent,
)
from nexus.company.brain.ontology_models import (
    BrainEntity,
    BrainEntityEvidence,
    BrainEntityRevision,
    BrainRelationshipEvidence,
    BrainRelationshipRevision,
)
from nexus.company.brain.publication_contracts import RelationshipPublication
from nexus.company.brain.publication_evidence import PublicationEvidence
from nexus.company.brain.relationships import RelationshipRecord
from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.company.brain.sources import EvidenceRef
from nexus.company.contracts.results import VerificationResult
from nexus.company.directory_models import DirectoryMembership, RegisteredWork
from nexus.execution.runtime_models import EffectIntent
from nexus.harness.journal_models import JournalAction

_CONTENT: TypeAdapter[EntityContent] = TypeAdapter(EntityContent)


async def native_content(
    session: AsyncSession,
    scope: BrainReadScope,
    content: EntityContent,
    evidence: PublicationEvidence,
) -> None:
    """Reference existence and exact readable evidence never mint native execution permissions."""
    valid = True
    if isinstance(content, PrincipalContent):
        valid = (
            await session.get(DirectoryMembership, (scope.company_id, content.principal_id))
            is not None
        )
    elif isinstance(content, WorkItemContent):
        valid = await session.get(RegisteredWork, (scope.company_id, content.task_id)) is not None
    elif isinstance(content, EvidenceContent):
        valid = content.evidence_id in {row.record.evidence_id for row in evidence.materials}
    elif isinstance(content, ArtifactContent):
        valid = content.artifact_revision_id in {
            row.record.artifact.artifact_revision_id for row in evidence.materials
        }
    elif isinstance(content, ActionContent):
        valid = (
            await session.scalar(
                select(JournalAction.id).where(
                    JournalAction.company_id == scope.company_id,
                    JournalAction.id == content.action_id,
                )
            )
            is not None
        )
    elif isinstance(content, VerificationContent):
        await exact_verification(session, scope, content.verification_id)
    if not valid:
        raise BrainDeniedError("Native ontology reference is unavailable in this company")


async def exact_verification(
    session: AsyncSession, scope: BrainReadScope, verification_id: UUID
) -> VerificationResult:
    rows = (
        await session.execute(
            select(EffectIntent.verification_json, EffectIntent.action_id)
            .where(
                EffectIntent.company_id == scope.company_id,
                cast(EffectIntent.verification_json, JSONB)["verification_id"].astext
                == str(verification_id),
            )
            .limit(2)
        )
    ).all()
    if len(rows) != 1 or rows[0][0] is None:
        raise BrainDeniedError("Native verification reference is unavailable")
    saved, action_id = rows[0]
    try:
        value = VerificationResult.model_validate_json(saved)
    except ValidationError as exc:
        raise BrainDeniedError("Native verification reference is unavailable") from exc
    if (
        value.company_id != scope.company_id
        or value.verification_id != verification_id
        or value.action_id != action_id
    ):
        raise BrainDeniedError("Native verification reference is unavailable")
    return value


async def entity_record(
    session: AsyncSession, entity: BrainEntity, row: BrainEntityRevision
) -> EntityRevisionRecord:
    keys = tuple(
        (
            await session.scalars(
                select(BrainEntityEvidence.evidence_id)
                .where(
                    BrainEntityEvidence.company_id == row.company_id,
                    BrainEntityEvidence.entity_revision_id == row.entity_revision_id,
                )
                .order_by(BrainEntityEvidence.evidence_id)
            )
        ).all()
    )
    return EntityRevisionRecord.model_validate(
        {
            "company_id": row.company_id,
            "entity_id": row.entity_id,
            "entity_revision_id": row.entity_revision_id,
            "revision": row.revision,
            "kind": row.kind,
            "resource": ResourceRef(company_id=row.company_id, resource_id=entity.resource_id),
            "content": _CONTENT.validate_json(row.content_json),
            "evidence": tuple(
                EvidenceRef(company_id=row.company_id, evidence_id=key) for key in keys
            ),
            "source_event": SourceTime.model_validate_json(row.source_event_json),
            "ingested_at": row.ingested_at,
            "validity": ValidityInterval(start=row.validity_start, end=row.validity_end),
            "origin": row.origin,
            "status": row.status,
        }
    )


async def exact_entity(
    session: AsyncSession, scope: BrainReadScope, ref: EntityRevisionRef
) -> EntityRevisionRecord:
    entity = await session.get(BrainEntity, (scope.company_id, ref.entity_id))
    row = await session.get(BrainEntityRevision, (scope.company_id, ref.entity_revision_id))
    if (
        ref.company_id != scope.company_id
        or entity is None
        or row is None
        or entity.current_revision_id != ref.entity_revision_id
        or (row.entity_id, row.kind, row.revision) != (ref.entity_id, ref.kind, ref.revision)
    ):
        raise BrainDeniedError("Exact current ontology endpoint is unavailable")
    return await entity_record(session, entity, row)


async def relationship_record(
    session: AsyncSession,
    row: BrainRelationshipRevision,
    subject: EntityRevisionRecord,
    object_: EntityRevisionRecord,
) -> RelationshipRecord:
    expected_subject = (subject.entity_id, subject.entity_revision_id, subject.kind)
    expected_object = (object_.entity_id, object_.entity_revision_id, object_.kind)
    if (row.subject_id, row.subject_revision_id, row.subject_kind) != expected_subject or (
        row.object_id,
        row.object_revision_id,
        row.object_kind,
    ) != expected_object:
        raise BrainConflictError("Stored ontology relationship endpoints cannot be rebound")
    keys = tuple(
        (
            await session.scalars(
                select(BrainRelationshipEvidence.evidence_id)
                .where(
                    BrainRelationshipEvidence.company_id == row.company_id,
                    BrainRelationshipEvidence.relationship_revision_id
                    == row.relationship_revision_id,
                )
                .order_by(BrainRelationshipEvidence.evidence_id)
            )
        ).all()
    )
    return RelationshipRecord.model_validate(
        {
            "company_id": row.company_id,
            "relationship_id": row.relationship_id,
            "relationship_revision_id": row.relationship_revision_id,
            "revision": row.revision,
            "predicate": row.predicate,
            "subject": EntityRevisionRef.model_validate_json(
                subject.model_dump_json(include=set(EntityRevisionRef.model_fields))
            ),
            "object": EntityRevisionRef.model_validate_json(
                object_.model_dump_json(include=set(EntityRevisionRef.model_fields))
            ),
            "evidence": tuple(
                EvidenceRef(company_id=row.company_id, evidence_id=key) for key in keys
            ),
            "origin": row.origin,
            "status": row.status,
            "validity": ValidityInterval(start=row.validity_start, end=row.validity_end),
            "recorded_at": row.recorded_at,
        }
    )


def publication_origin(model: bool, report: bool) -> Literal["operator", "source", "model"]:
    return "model" if model else "source" if report else "operator"


async def publish_relationship(
    session: AsyncSession,
    command: RelationshipPublication,
    subject: EntityRevisionRecord,
    object_: EntityRevisionRecord,
    now: datetime,
    *,
    model: bool,
    report: bool,
) -> RelationshipRecord:
    origin = publication_origin(model, report)
    value = RelationshipRecord(
        company_id=command.company_id,
        relationship_id=command.relationship_id,
        relationship_revision_id=uuid5(
            command.company_id,
            json.dumps(("relationship", str(command.relationship_id), command.revision, origin)),
        ),
        revision=command.revision,
        predicate=command.predicate,
        subject=EntityRevisionRef.model_validate_json(
            subject.model_dump_json(include=set(EntityRevisionRef.model_fields))
        ),
        object=EntityRevisionRef.model_validate_json(
            object_.model_dump_json(include=set(EntityRevisionRef.model_fields))
        ),
        evidence=tuple(sorted(command.evidence, key=lambda ref: ref.evidence_id)),
        validity=command.validity,
        origin=origin,
        status="source_report" if report else "proposed",
        recorded_at=now,
    )
    prior_row = await session.scalar(
        select(BrainRelationshipRevision).where(
            BrainRelationshipRevision.company_id == value.company_id,
            BrainRelationshipRevision.relationship_id == value.relationship_id,
            BrainRelationshipRevision.revision == value.revision,
        )
    )
    if prior_row is not None:
        prior = await relationship_record(session, prior_row, subject, object_)
        if prior.model_dump(exclude={"recorded_at"}) != value.model_dump(exclude={"recorded_at"}):
            raise BrainConflictError("Relationship revision identity cannot be rebound")
        return prior
    session.add(
        BrainRelationshipRevision(
            company_id=value.company_id,
            relationship_id=value.relationship_id,
            relationship_revision_id=value.relationship_revision_id,
            revision=value.revision,
            predicate=value.predicate,
            subject_id=value.subject.entity_id,
            subject_revision_id=value.subject.entity_revision_id,
            subject_kind=value.subject.kind,
            object_id=value.object.entity_id,
            object_revision_id=value.object.entity_revision_id,
            object_kind=value.object.kind,
            origin=value.origin,
            status=value.status,
            validity_start=value.validity.start,
            validity_end=value.validity.end,
            recorded_at=value.recorded_at,
        )
    )
    await session.flush()
    for ref in value.evidence:
        session.add(
            BrainRelationshipEvidence(
                company_id=value.company_id,
                relationship_revision_id=value.relationship_revision_id,
                evidence_id=ref.evidence_id,
            )
        )
    await session.flush()
    return value
