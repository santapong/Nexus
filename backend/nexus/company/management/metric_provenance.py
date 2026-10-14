"""Complete current artifact/source/resource qualification for protected metric facts."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.source_models import BrainSourceHead, BrainSourceRevision
from nexus.company.brain.sources import ArtifactRevisionRef, SourceHead, SourceRevisionRef
from nexus.company.management.acceptance_provenance import reference_sources
from nexus.company.management.base import SourceTime
from nexus.company.management.control_support import db_clock
from nexus.company.management.metric_contracts import MetricSourceFact, MetricWorkFact
from nexus.company.management.owner_view_sources import (
    OwnerViewSources,
    owner_brain_scope,
    source_disclosure,
)
from nexus.company.management.transactions import ManagementDeniedError
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True)
class ProtectedMetricFacts:
    resources: tuple[UUID, ...]
    sources: tuple[MetricSourceFact, ...]
    deadlines: tuple[datetime, ...]


async def protect_facts(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    services: OwnerViewSources,
    facts: tuple[MetricWorkFact, ...],
    baseline: tuple[ArtifactRevisionRef, ...],
    selected_resources: tuple[UUID, ...],
) -> ProtectedMetricFacts | None:
    roots = {row.artifact_revision_id: row for fact in facts for row in fact.artifacts}
    roots.update({row.artifact_revision_id: row for row in baseline})
    resources = set(selected_resources)
    ids: set[UUID] = set()
    deadlines: list[datetime] = []
    brain = owner_brain_scope(scope, identity)
    try:
        for reference in roots.values():
            visible = await source_disclosure(
                session, control, scope, identity, services, (reference,)
            )
            if visible is None:
                return None
            if visible.valid_until is not None:
                deadlines.append(visible.valid_until)
            source_ids, resource_ids = await reference_sources(session, brain, (reference,))
            resources.update(resource_ids)
            ids.update(source_ids)
        grants = await require_resources(
            session, brain, tuple(sorted(resources)), await db_clock(session)
        )
        deadlines.extend(row.expires_at for row in grants if row.expires_at is not None)
        sources = tuple([await source_fact(session, scope, item) for item in sorted(ids)])
        deadlines.extend(
            row.head.fresh_until for row in sources if row.head.fresh_until is not None
        )
        return ProtectedMetricFacts(tuple(sorted(resources)), sources, tuple(deadlines))
    except ValueError:
        return None


async def source_fact(
    session: AsyncSession,
    scope: CompanyControlScope,
    source_id: UUID,
) -> MetricSourceFact:
    head = await session.get(BrainSourceHead, (scope.company_id, source_id))
    row = (
        await session.get(BrainSourceRevision, (scope.company_id, head.current_revision_id))
        if head
        else None
    )
    if head is None or row is None or row.source_id != source_id:
        raise ManagementDeniedError("Metric protected source date is unavailable")
    revision = SourceRevisionRef(
        company_id=scope.company_id,
        source_id=source_id,
        source_revision_id=row.source_revision_id,
        revision=row.revision,
    )
    return MetricSourceFact(
        company_id=scope.company_id,
        source=revision,
        head=SourceHead.model_validate(
            {
                "company_id": scope.company_id,
                "source_id": source_id,
                "current": revision,
                "generation": head.generation,
                "observed_at": head.observed_at,
                "fresh_until": head.fresh_until,
                "availability": head.availability,
            }
        ),
        source_event=SourceTime.model_validate(
            {
                "precision": row.source_event_precision,
                "value": row.source_event_value,
                "basis": row.source_event_basis,
            }
        ),
        ingested_at=row.ingested_at,
    )
