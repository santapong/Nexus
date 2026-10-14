"""Actual native charter/artifact/source closure for owner notification disclosures."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.models import (
    BrainArtifactRevision,
    BrainSource,
    BrainSourceHead,
    BrainSourceRevision,
)
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.control_support import charter_record
from nexus.company.management.governance_models import ManagementCharterRevision
from nexus.company.management.operating_report_resources import report_resources
from nexus.company.management.plan_support import CurrentPlanBinding, PlanAdmissionCatalog
from nexus.company.notifications.contracts import NotificationProvenance
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.execution.runtime_support import db_now


async def native_provenance(
    session: AsyncSession,
    scope: BrainReadScope,
    binding: CurrentPlanBinding,
    catalog: PlanAdmissionCatalog,
    freshness: RegisteredSourceFreshness,
    output_refs: tuple[ArtifactRevisionRef, ...],
    native_sha256: str,
) -> NotificationProvenance:
    charter = await session.get(
        ManagementCharterRevision, (scope.company_id, binding.child.charter.revision_id)
    )
    if charter is None or catalog.company_id != scope.company_id:
        raise NotificationUnavailableError("Native notification source scope is unavailable")
    record = await charter_record(session, charter)
    resources = {row.symbol: row.resource.resource_id for row in catalog.resources}
    if not set(record.charter.resource_scopes) <= resources.keys():
        raise NotificationUnavailableError("Native notification source scope is unavailable")
    direct = tuple(sorted({resources[key] for key in record.charter.resource_scopes}))
    source_artifacts = await _source_artifacts(session, scope, direct)
    refs = {row.artifact_revision_id: row for row in output_refs}
    for row in source_artifacts:
        refs[row.artifact_revision_id] = ArtifactRevisionRef(
            company_id=row.company_id,
            artifact_id=row.artifact_id,
            artifact_revision_id=row.artifact_revision_id,
            revision=row.revision,
            sha256=row.sha256,
            byte_length=row.byte_length,
        )
    references = tuple(refs[key] for key in sorted(refs))
    if not references:
        raise NotificationUnavailableError("Native notification source scope is unavailable")
    required, _, heads = await report_resources(session, scope, direct, references)
    await freshness.revalidate_references(session, scope, references, await db_now(session))
    grants = await require_resources(session, scope, required, await db_now(session))
    deadlines = tuple(row.expires_at for row in grants if row.expires_at is not None)
    deadlines += tuple(row.fresh_until for row in heads if row.fresh_until is not None)
    return NotificationProvenance(
        company_id=scope.company_id,
        required_resource_ids=required,
        artifacts=references,
        source_heads=heads,
        protection_deadlines=deadlines,
        native_snapshot_sha256=native_sha256,
    )


async def _source_artifacts(
    session: AsyncSession, scope: BrainReadScope, direct: tuple[UUID, ...]
) -> tuple[BrainArtifactRevision, ...]:
    await require_resources(session, scope, direct, await db_now(session))
    source_artifacts = (
        await session.scalars(
            select(BrainArtifactRevision)
            .join(
                BrainSourceRevision,
                (BrainSourceRevision.company_id == BrainArtifactRevision.company_id)
                & (
                    BrainSourceRevision.artifact_revision_id
                    == BrainArtifactRevision.artifact_revision_id
                ),
            )
            .join(
                BrainSourceHead,
                (BrainSourceHead.company_id == BrainSourceRevision.company_id)
                & (BrainSourceHead.current_revision_id == BrainSourceRevision.source_revision_id),
            )
            .join(
                BrainSource,
                (BrainSource.company_id == BrainSourceRevision.company_id)
                & (BrainSource.source_id == BrainSourceRevision.source_id),
            )
            .where(BrainSource.company_id == scope.company_id, BrainSource.resource_id.in_(direct))
            .limit(34)
        )
    ).all()
    if len(source_artifacts) > 33:
        raise NotificationUnavailableError("Native notification source scope exceeds its bound")
    return tuple(source_artifacts)
