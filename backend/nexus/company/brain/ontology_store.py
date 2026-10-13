"""Owner source-report and actor proposal publication over the closed existing ontology."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_store import append_event
from nexus.company.brain.ontology import EntityRevisionRecord
from nexus.company.brain.ontology_models import (
    BrainEntity,
    BrainEntityEvidence,
    BrainEntityRevision,
)
from nexus.company.brain.ontology_support import (
    entity_record,
    exact_entity,
    native_content,
    publication_origin,
    publish_relationship,
)
from nexus.company.brain.publication_contracts import EntityPublication, RelationshipPublication
from nexus.company.brain.publication_evidence import (
    prepare_evidence,
    recheck_publication,
    require_mutation,
    require_source_report,
)
from nexus.company.brain.relationships import RelationshipRecord
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import (
    BrainConflictError,
    BrainDeniedError,
    brain_transaction,
)


class BrainOntologyStore:
    def __init__(
        self, factory: async_sessionmaker[AsyncSession], retriever: PersistentBrainRetriever
    ) -> None:
        self.factory, self.retriever = factory, retriever

    async def publish_manual_entity(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        command: EntityPublication,
        *,
        source_report: bool = False,
    ) -> EntityRevisionRecord:
        require_source_report(source_report, command.evidence)
        return await self._entity(scope, identity, command, model=False, report=source_report)

    async def propose_entity(
        self, scope: BrainReadScope, identity: VerifiedIdentity, command: EntityPublication
    ) -> EntityRevisionRecord:
        return await self._entity(scope, identity, command, model=True, report=False)

    async def publish_manual_relationship(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        command: RelationshipPublication,
        *,
        source_report: bool = False,
    ) -> RelationshipRecord:
        require_source_report(source_report, command.evidence)
        return await self._relationship(scope, identity, command, model=False, report=source_report)

    async def propose_relationship(
        self, scope: BrainReadScope, identity: VerifiedIdentity, command: RelationshipPublication
    ) -> RelationshipRecord:
        return await self._relationship(scope, identity, command, model=True, report=False)

    async def _entity(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        command: EntityPublication,
        *,
        model: bool,
        report: bool,
    ) -> EntityRevisionRecord:
        command = EntityPublication.model_validate_json(command.model_dump_json())
        if command.company_id != scope.company_id:
            raise BrainDeniedError("Ontology publication is unavailable")
        async with brain_transaction(self.factory, scope, identity, owner=not model) as (
            session,
            control,
            _,
        ):
            await require_mutation(session, control, scope, identity, model=model)
        prepared = await prepare_evidence(self.retriever, scope, identity, command.evidence)
        resources = (command.resource.resource_id,)
        async with brain_transaction(self.factory, scope, identity, owner=not model) as (
            session,
            control,
            _,
        ):
            now = await recheck_publication(
                self.retriever, session, control, scope, identity, prepared, resources, model=model
            )
            await native_content(session, scope, command.content, prepared)
            value = await _publish_entity(session, command, now, model=model, report=report)
            await append_event(
                session,
                scope,
                kind="claims_changed",
                resource_id=command.resource.resource_id,
                deduplication_key=f"entity:{value.entity_revision_id}",
                now=value.ingested_at,
            )
            await recheck_publication(
                self.retriever, session, control, scope, identity, prepared, resources, model=model
            )
            return value

    async def _relationship(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        command: RelationshipPublication,
        *,
        model: bool,
        report: bool,
    ) -> RelationshipRecord:
        command = RelationshipPublication.model_validate_json(command.model_dump_json())
        if command.company_id != scope.company_id:
            raise BrainDeniedError("Ontology relationship is unavailable")
        if report and command.predicate == "verified_by":
            raise BrainDeniedError("Stored verification candidates cannot establish acceptance")
        async with brain_transaction(self.factory, scope, identity, owner=not model) as (
            session,
            control,
            _,
        ):
            await require_mutation(session, control, scope, identity, model=model)
            subject, object_ = (
                await exact_entity(session, scope, command.subject),
                await exact_entity(session, scope, command.object),
            )
        references = tuple(
            sorted(
                set(command.evidence + subject.evidence + object_.evidence),
                key=lambda ref: ref.evidence_id,
            )
        )
        prepared = await prepare_evidence(self.retriever, scope, identity, references)
        resources = tuple(sorted({subject.resource.resource_id, object_.resource.resource_id}))
        async with brain_transaction(self.factory, scope, identity, owner=not model) as (
            session,
            control,
            _,
        ):
            await exact_entity(session, scope, command.subject)
            await exact_entity(session, scope, command.object)
            now = await recheck_publication(
                self.retriever, session, control, scope, identity, prepared, resources, model=model
            )
            value = await publish_relationship(
                session, command, subject, object_, now, model=model, report=report
            )
            await append_event(
                session,
                scope,
                kind="claims_changed",
                resource_id=subject.resource.resource_id,
                deduplication_key=f"relationship:{value.relationship_revision_id}",
                now=value.recorded_at,
            )
            await recheck_publication(
                self.retriever, session, control, scope, identity, prepared, resources, model=model
            )
            return value


async def _publish_entity(
    session: AsyncSession, command: EntityPublication, now: datetime, *, model: bool, report: bool
) -> EntityRevisionRecord:
    origin = publication_origin(model, report)
    value = EntityRevisionRecord(
        company_id=command.company_id,
        entity_id=command.entity_id,
        entity_revision_id=uuid5(
            command.company_id,
            json.dumps(("entity", str(command.entity_id), command.revision, origin)),
        ),
        kind=command.content.kind,
        revision=command.revision,
        resource=command.resource,
        content=command.content,
        evidence=tuple(sorted(command.evidence, key=lambda ref: ref.evidence_id)),
        source_event=command.source_event,
        ingested_at=now,
        validity=command.validity,
        origin=origin,
        status="source_report" if report else "proposed",
    )
    entity = await session.get(BrainEntity, (command.company_id, command.entity_id))
    previous = await session.scalar(
        select(BrainEntityRevision).where(
            BrainEntityRevision.company_id == command.company_id,
            BrainEntityRevision.entity_id == command.entity_id,
            BrainEntityRevision.revision == command.revision,
        )
    )
    if previous is not None:
        if entity is None:
            raise BrainDeniedError("Ontology identity is unavailable")
        prior = await entity_record(session, entity, previous)
        if prior.model_dump(exclude={"ingested_at"}) != value.model_dump(exclude={"ingested_at"}):
            raise BrainConflictError("Entity revision identity cannot be rebound")
        return prior
    if entity is not None and (entity.kind, entity.resource_id) != (
        command.content.kind,
        command.resource.resource_id,
    ):
        raise BrainConflictError("Logical entity kind/resource cannot be rebound")
    current = entity.current_revision_id if entity else None
    if current != command.expected_previous_revision_id:
        raise BrainConflictError("Current entity head changed; reload before publication")
    if entity is None:
        entity = BrainEntity(
            company_id=value.company_id,
            entity_id=value.entity_id,
            resource_id=value.resource.resource_id,
            kind=value.kind,
            recorded_at=now,
        )
        session.add(entity)
        await session.flush()
    session.add(
        BrainEntityRevision(
            company_id=value.company_id,
            entity_id=value.entity_id,
            entity_revision_id=value.entity_revision_id,
            kind=value.kind,
            revision=value.revision,
            content_json=value.content.model_dump_json(),
            source_event_json=value.source_event.model_dump_json(),
            ingested_at=value.ingested_at,
            validity_start=value.validity.start,
            validity_end=value.validity.end,
            origin=value.origin,
            status=value.status,
        )
    )
    await session.flush()
    for ref in value.evidence:
        session.add(
            BrainEntityEvidence(
                company_id=value.company_id,
                entity_revision_id=value.entity_revision_id,
                evidence_id=ref.evidence_id,
            )
        )
    entity.current_revision_id = value.entity_revision_id
    await session.flush()
    return value
