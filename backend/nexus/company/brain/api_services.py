"""Read-only HTTP dependencies and server-derived Brain scope; no execution intake."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Self
from uuid import UUID, uuid4

from pydantic import Field, StringConstraints, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import (
    Capability,
    CompanyDirectory,
    VerifiedIdentity,
    bind_work_scope,
    resolve_principal_access,
)
from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope, Flag, Name, ValueContract
from nexus.company.brain.claims import ClaimKind
from nexus.company.brain.context import ContextSelection, SectionSelection
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.models import BrainEntity, BrainEntityEvidence, BrainEntityRevision
from nexus.company.brain.ontology import EntityRevisionRecord
from nexus.company.brain.retrieval import SearchRequest
from nexus.company.brain.retrieval_graph import visible_entities
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import (
    BrainConflictError,
    BrainDeniedError,
    brain_transaction,
)
from nexus.company.brain.sources import EvidenceRef


class WorkBinding(ValueContract):
    """Optional registered work hints; actual actor and audit IDs come from the server."""

    task_id: UUID | None = None
    task_trace_id: UUID | None = None

    @model_validator(mode="after")
    def complete_work(self) -> Self:
        if (self.task_id is None) != (self.task_trace_id is None):
            raise ValueError("A work read requires its registered task and trace")
        return self


class SearchQuery(ValueContract):
    query: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    explicit_evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=32)
    entity_ids: tuple[UUID, ...] = Field(default=(), max_length=32)
    claim_kinds: tuple[ClaimKind, ...] = Field(default=(), max_length=6)
    include_history: Flag = False

    def selection(self, company_id: UUID) -> SearchRequest:
        """Path company is a lookup hint checked against current signed-directory scope."""
        return SearchRequest(company_id=company_id, **self.model_dump())


class SearchRead(WorkBinding):
    search: SearchQuery


class SectionQuery(ValueContract):
    artifact_revision_id: UUID
    sections: tuple[Name, ...] = Field(min_length=1, max_length=20)


class ContextRead(WorkBinding):
    search: SearchQuery | None = None
    explicit_evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=32)
    explicit_sections: tuple[SectionQuery, ...] = Field(default=(), max_length=20)
    attachments: tuple[UUID, ...] = Field(default=(), max_length=20)
    workspace_files: tuple[UUID, ...] = Field(default=(), max_length=20)

    def selection(self, company_id: UUID) -> ContextSelection:
        """Construct exact references without accepting caller class, ACL or budget fields."""
        return ContextSelection(
            company_id=company_id,
            search=self.search.selection(company_id) if self.search else None,
            explicit_evidence_ids=self.explicit_evidence_ids,
            explicit_sections=tuple(
                SectionSelection(company_id=company_id, **row.model_dump())
                for row in self.explicit_sections
            ),
            attachments=tuple(
                EvidenceRef(company_id=company_id, evidence_id=key) for key in self.attachments
            ),
            workspace_files=tuple(
                EvidenceRef(company_id=company_id, evidence_id=key) for key in self.workspace_files
            ),
        )


@dataclass(frozen=True, slots=True)
class BrainServices:
    """Separate opt-in dependencies; production factories must choose trusted providers."""

    directory: CompanyDirectory
    retriever: PersistentBrainRetriever
    assembler: PersistentContextAssembler


async def resolve_brain_read(
    directory: CompanyDirectory,
    identity: VerifiedIdentity,
    company_id: UUID,
    binding: WorkBinding,
) -> BrainReadScope:
    """Initial fresh directory check; every service rechecks under CompanyControl."""
    operation_id, trace_id = uuid4(), uuid4()
    access = await resolve_principal_access(
        identity,
        directory,
        company_id=company_id,
        capability=Capability.READ,
        task_id=operation_id,
        trace_id=trace_id,
    )
    actor_id: UUID | None = None
    if binding.task_id is not None and binding.task_trace_id is not None:
        work = await directory.lookup_work(
            company_id, binding.task_id, trace_id=binding.task_trace_id
        )
        bind_work_scope(
            access,
            work,
            task_id=binding.task_id,
            trace_id=binding.task_trace_id,
            capability=Capability.READ,
        )
        assert work is not None  # The shared policy rejects absent registered work.
        actor_id = work.actor_id
    return BrainReadScope(
        company_id=access.company_id,
        workspace_id=access.workspace_id,
        principal_id=access.principal_id,
        operation_id=operation_id,
        trace_id=trace_id,
        task_id=binding.task_id,
        task_trace_id=binding.task_trace_id,
        actor_id=actor_id,
    )


async def current_entity(
    services: BrainServices, scope: BrainReadScope, identity: VerifiedIdentity, entity_id: UUID
) -> EntityRevisionRecord:
    """Materialize every evidence contributor before final entity/policy publication."""
    async with brain_transaction(services.retriever.factory, scope, identity) as (session, _, now):
        record, resources = await _entity_snapshot(session, scope, entity_id, now)
    handles = await services.retriever.citation_handles(
        scope, identity, tuple(row.evidence_id for row in record.evidence), include_history=True
    )
    materials = await services.retriever.materialize(scope, identity, handles)
    if any(row.source_state == "historical" or row.freshness == "stale" for row in materials):
        raise BrainConflictError("Brain entity support changed; refresh the current entity")
    async with brain_transaction(services.retriever.factory, scope, identity) as (
        session,
        control,
        now,
    ):
        await services.retriever.revalidate_handles(session, control, scope, identity, handles, now)
        current, current_resources = await _entity_snapshot(
            session, scope, entity_id, await _entity_clock(session)
        )
        if current != record or current_resources != resources:
            raise BrainConflictError("Brain entity changed; refresh the read")
    return record


async def _entity_snapshot(
    session: AsyncSession, scope: BrainReadScope, entity_id: UUID, now: datetime
) -> tuple[EntityRevisionRecord, tuple[ResourceGeneration, ...]]:
    entity = await session.scalar(
        select(BrainEntity).where(
            BrainEntity.company_id == scope.company_id,
            BrainEntity.entity_id == entity_id,
            BrainEntity.entity_id.in_(visible_entities(scope, now)),
        )
    )
    revision = (
        await session.get(BrainEntityRevision, (scope.company_id, entity.current_revision_id))
        if entity is not None
        else None
    )
    if entity is None or revision is None:
        raise BrainDeniedError("Brain entity is unavailable")
    ids = tuple(
        (
            await session.scalars(
                select(BrainEntityEvidence.evidence_id)
                .where(
                    BrainEntityEvidence.company_id == scope.company_id,
                    BrainEntityEvidence.entity_revision_id == revision.entity_revision_id,
                )
                .order_by(BrainEntityEvidence.evidence_id)
                .limit(33)
            )
        ).all()
    )
    if len(ids) > 32:
        raise BrainDeniedError("Brain entity evidence exceeds its boundary")
    resources = await require_resources(
        session, scope, (entity.resource_id,), await _entity_clock(session)
    )
    return _entity_record(scope, entity, revision, ids), resources


async def _entity_clock(session: AsyncSession) -> datetime:
    now: datetime | None = await session.scalar(select(func.clock_timestamp()))
    if now is None or now.utcoffset() is None:
        raise BrainDeniedError("Brain entity clock is unavailable")
    return now


def _entity_record(
    scope: BrainReadScope, entity: BrainEntity, revision: BrainEntityRevision, ids: tuple[UUID, ...]
) -> EntityRevisionRecord:
    return EntityRevisionRecord.model_validate_json(
        json.dumps(
            {
                "company_id": str(scope.company_id),
                "entity_id": str(entity.entity_id),
                "entity_revision_id": str(revision.entity_revision_id),
                "kind": revision.kind,
                "revision": revision.revision,
                "resource": {
                    "company_id": str(scope.company_id),
                    "resource_id": str(entity.resource_id),
                },
                "content": json.loads(revision.content_json),
                "evidence": [
                    {"company_id": str(scope.company_id), "evidence_id": str(key)} for key in ids
                ],
                "source_event": json.loads(revision.source_event_json),
                "ingested_at": revision.ingested_at.isoformat(),
                "validity": {
                    "start": revision.validity_start.isoformat()
                    if revision.validity_start
                    else None,
                    "end": revision.validity_end.isoformat() if revision.validity_end else None,
                },
                "origin": revision.origin,
                "status": revision.status,
            }
        )
    )
