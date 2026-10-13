"""Actual citation bytes precede final current owner/actor and output-reader publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import (
    AccessDeniedError,
    Capability,
    VerifiedIdentity,
    WorkAccess,
    bind_work_scope,
    require_capability,
)
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.derivation_support import _recipients
from nexus.company.brain.retrieval import CitationHandle, MaterializedEvidence
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.brain.scope_support import (
    BrainConflictError,
    BrainDeniedError,
    require_brain_scope,
)
from nexus.company.brain.source_models import BrainSource
from nexus.company.brain.sources import EvidenceRef
from nexus.company.directory_models import RegisteredWork, WorkPrincipal
from nexus.company.directory_store import _lineage_active
from nexus.harness.journal_models import CompanyControl

_CLASSIFICATION = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


@dataclass(frozen=True)
class PublicationEvidence:
    handles: tuple[CitationHandle, ...]
    materials: tuple[MaterializedEvidence, ...]


async def prepare_evidence(
    retriever: PersistentBrainRetriever,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    references: tuple[EvidenceRef, ...],
) -> PublicationEvidence:
    if len(references) > 32 or any(row.company_id != scope.company_id for row in references):
        raise BrainDeniedError("Publication evidence exceeds its boundary")
    ids = tuple(sorted({row.evidence_id for row in references}))
    handles: list[CitationHandle] = []
    materials: list[MaterializedEvidence] = []
    for offset in range(0, len(ids), retriever.limits.max_results):
        selected = await retriever.citation_handles(
            scope,
            identity,
            ids[offset : offset + retriever.limits.max_results],
            include_history=False,
        )
        handles.extend(selected)
        materials.extend(await retriever.materialize(scope, identity, selected))
    return PublicationEvidence(tuple(handles), tuple(materials))


async def require_mutation(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    *,
    model: bool,
) -> None:
    access = await require_brain_scope(session, control, scope, identity, owner=not model)
    if not model:
        return
    if scope.task_id is None or scope.task_trace_id is None or scope.actor_id != scope.principal_id:
        raise BrainDeniedError("Model knowledge proposals require their current registered actor")
    row = await session.get(RegisteredWork, (scope.company_id, scope.task_id))
    if row is None or control.paused:
        raise BrainDeniedError("Model knowledge proposal scope is unavailable")
    principals = tuple(
        (
            await session.scalars(
                select(WorkPrincipal.principal_id).where(
                    WorkPrincipal.company_id == scope.company_id,
                    WorkPrincipal.task_id == scope.task_id,
                )
            )
        ).all()
    )
    try:
        require_capability(access, Capability.INTERNAL_PROPOSAL)
        bind_work_scope(
            access,
            WorkAccess(
                company_id=row.company_id,
                workspace_id=row.workspace_id,
                task_id=row.task_id,
                trace_id=row.trace_id,
                actor_id=row.actor_id,
                active=await _lineage_active(session, row),
                allowed_principals=principals,
            ),
            task_id=scope.task_id,
            trace_id=scope.task_trace_id,
            capability=Capability.INTERNAL_PROPOSAL,
        )
    except AccessDeniedError as exc:
        raise BrainDeniedError("Model knowledge proposal scope is unavailable") from exc


async def recheck_publication(
    retriever: PersistentBrainRetriever,
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    prepared: PublicationEvidence,
    resource_ids: tuple[UUID, ...],
    *,
    model: bool,
) -> datetime:
    await require_mutation(session, control, scope, identity, model=model)
    now: datetime | None = await session.scalar(select(func.clock_timestamp()))
    if now is None or now.utcoffset() is None:
        raise BrainDeniedError("Publication clock is unavailable")
    await retriever.revalidate_handles(session, control, scope, identity, prepared.handles, now)
    for handle in prepared.handles:
        by_source = {head.source_id: head for head in handle.source_heads}
        for ref in handle.source_contributors:
            head = by_source[ref.source_id]
            if (
                head.current != ref
                or head.availability != "available"
                or (head.fresh_until is not None and head.fresh_until <= now)
            ):
                raise BrainConflictError("Publication source changed or is unavailable")
    resources = tuple(sorted(set(resource_ids)))
    await require_resources(session, scope, resources, now)
    input_resources = tuple(
        sorted(
            {
                resource.resource_id
                for handle in prepared.handles
                for resource in handle.contributors
            }
        )
    )
    classification = max(
        (_CLASSIFICATION[row.data_classification] for row in prepared.materials), default=0
    )
    for resource_id in resources:
        source = await session.scalar(
            select(BrainSource).where(
                BrainSource.company_id == scope.company_id, BrainSource.resource_id == resource_id
            )
        )
        if source is None or _CLASSIFICATION[source.data_classification] < classification:
            raise BrainDeniedError("Publication output classification is unavailable")
        await _recipients(session, scope, resource_id, input_resources, now)
    return now


def require_source_report(source_report: bool, evidence: tuple[EvidenceRef, ...]) -> None:
    if type(source_report) is not bool or (source_report and not evidence):
        raise BrainDeniedError("A source report requires literal mode and exact source evidence")
