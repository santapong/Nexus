"""Current complete resource ACLs precede report facts, including historical expense audit."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_support import require_resources
from nexus.company.brain.artifact_input_support import artifact_input_closure
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.models import (
    BrainArtifactRevision,
    BrainSource,
    BrainSourceHead,
    BrainSourceRevision,
)
from nexus.company.brain.retrieval_records import contributors, heads
from nexus.company.brain.retrieval_sql import eligible_sources
from nexus.company.brain.sources import ArtifactRevisionRef, SourceHead, SourceRevisionRef
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_provenance import artifact_roots, exact_artifact
from nexus.company.management.control_support import charter_record
from nexus.company.management.governance_models import ManagementCharterRevision
from nexus.company.management.operating_report_bindings import native_declarations
from nexus.company.management.operating_report_contracts import ReportSelection
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.execution.runtime_support import db_now


async def report_resources(
    session: AsyncSession,
    scope: BrainReadScope,
    resource_ids: tuple[UUID, ...],
    references: tuple[ArtifactRevisionRef, ...],
) -> tuple[tuple[UUID, ...], tuple[tuple[UUID, int], ...], tuple[SourceHead, ...]]:
    """Historical refs remain auditable only through every currently granted contributor."""
    require_acceptance(
        len(references) <= 33
        and len(resource_ids) <= 32
        and sum(row.byte_length for row in references) <= 8_650_752
    )
    resources, revisions = await resource_roots(session, scope, resource_ids, references)
    require_acceptance(len(revisions) <= 64)
    allowed = (
        set(
            (
                await session.scalars(
                    eligible_sources(scope, await db_now(session)).where(
                        BrainSourceRevision.source_revision_id.in_(revisions)
                    )
                )
            ).all()
        )
        if revisions
        else set()
    )
    require_acceptance(allowed == revisions)
    refs: dict[UUID, SourceRevisionRef] = {}
    for revision_id in sorted(revisions):
        resolved, required, _ = await contributors(session, scope, revision_id)
        refs.update({row.source_revision_id: row for row in resolved})
        resources.update(required)
    require_acceptance(len(resources) <= 32 and len(refs) <= 64)
    current = await heads(session, scope, tuple(refs[key] for key in sorted(refs))) if refs else ()
    unique = {row.source_id: row for row in current}
    now = await db_now(session)
    grants = await require_resources(session, scope, tuple(sorted(resources)), now)
    final = await db_now(session)
    require_acceptance(all(row.expires_at is None or row.expires_at > final for row in grants))
    return (
        tuple(sorted(resources)),
        tuple((row.resource_id, row.generation) for row in grants),
        tuple(unique[key] for key in sorted(unique)),
    )


async def resource_roots(
    session: AsyncSession,
    scope: BrainReadScope,
    resource_ids: tuple[UUID, ...],
    references: tuple[ArtifactRevisionRef, ...],
) -> tuple[set[UUID], set[UUID]]:
    resources, revisions = set(resource_ids), set()
    for reference in references:
        artifact = await exact_artifact(session, scope, reference)
        lineage = await artifact_input_closure(session, scope, (artifact.artifact_revision_id,))
        resources.update(lineage.resource_ids)
        for identifier in lineage.artifact_revision_ids:
            parent = await session.get(BrainArtifactRevision, (scope.company_id, identifier))
            require_acceptance(parent is not None)
            assert parent is not None
            revisions.update(await artifact_roots(session, scope, parent))
    direct = (
        await session.scalars(
            select(BrainSourceRevision.source_revision_id)
            .join(
                BrainSource,
                (BrainSource.company_id == BrainSourceRevision.company_id)
                & (BrainSource.source_id == BrainSourceRevision.source_id),
            )
            .join(
                BrainSourceHead,
                (BrainSourceHead.company_id == BrainSourceRevision.company_id)
                & (BrainSourceHead.current_revision_id == BrainSourceRevision.source_revision_id),
            )
            .where(
                BrainSource.company_id == scope.company_id,
                BrainSource.resource_id.in_(resource_ids),
            )
        )
    ).all()
    # All direct revisions need not be current for history; their complete ACL remains mandatory.
    revisions.update(direct)
    return resources, revisions


async def selection_resources(
    session: AsyncSession,
    scope: BrainReadScope,
    selection: ReportSelection,
    catalog: PlanAdmissionCatalog,
) -> tuple[UUID, ...]:
    """Every selected native charter symbol resolves through the actual server resource map."""
    require_acceptance(catalog.company_id == scope.company_id)
    resource_map = {row.symbol: row.resource for row in catalog.resources}
    require_acceptance(len(resource_map) == len(catalog.resources))
    bindings = {row.task_id: row for row in (selection.author, selection.verifier, *selection.work)}
    resources = set()
    for binding in bindings.values():
        declarations = await native_declarations(session, scope.company_id, binding)
        for row in declarations:
            native = await session.get(
                ManagementCharterRevision, (scope.company_id, row.charter_revision_id)
            )
            require_acceptance(native is not None)
            assert native is not None
            charter = await charter_record(session, native)
            require_acceptance(set(charter.charter.resource_scopes) <= resource_map.keys())
            for symbol in charter.charter.resource_scopes:
                reference = resource_map[symbol]
                require_acceptance(reference.company_id == scope.company_id)
                resources.add(reference.resource_id)
    require_acceptance(len(resources) <= 32)
    return tuple(sorted(resources))
