"""Fresh final current-report scope, complete output ACL and selected-source time gate."""

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import revalidate_brain_scope
from nexus.company.brain.source_models import (
    BrainArtifactRevision,
    BrainSourceHead,
    BrainSourceRevision,
)
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.acceptance_provenance import reference_sources
from nexus.company.management.operating_report_contracts import ReportData
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


async def final_report_read(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    data: ReportData,
    output: ArtifactRevisionRef | None,
    freshness: RegisteredSourceFreshness,
) -> None:
    references = await current_source_artifacts(session, scope, data, output)
    source_ids, output_resources = await reference_sources(session, scope, references)
    heads = [await session.get(BrainSourceHead, (scope.company_id, key)) for key in source_ids]
    require_acceptance(all(row is not None for row in heads))
    resources = tuple(sorted(set(data.required_resource_ids) | set(output_resources)))
    await revalidate_brain_scope(session, control, scope, identity)
    grants = await require_resources(session, scope, resources, await db_now(session))
    await freshness.revalidate_references(session, scope, references, await db_now(session))
    final = await db_now(session)
    require_acceptance(all(row.expires_at is None or row.expires_at > final for row in grants))
    require_acceptance(
        all(
            row is not None
            and row.availability == "available"
            and (row.fresh_until is None or row.fresh_until > final)
            for row in heads
        )
    )


async def current_source_artifacts(
    session: AsyncSession,
    scope: BrainReadScope,
    data: ReportData,
    output: ArtifactRevisionRef | None,
) -> tuple[ArtifactRevisionRef, ...]:
    """Resolve current heads to real protected artifacts so nullable TTL requires server policy."""
    result = {output.artifact_revision_id: output} if output is not None else {}
    for head in data.source_heads:
        revision = await session.get(
            BrainSourceRevision, (scope.company_id, head.current.source_revision_id)
        )
        require_acceptance(revision is not None and revision.source_id == head.source_id)
        assert revision is not None
        artifact = await session.get(
            BrainArtifactRevision, (scope.company_id, revision.artifact_revision_id)
        )
        require_acceptance(artifact is not None)
        assert artifact is not None
        result[artifact.artifact_revision_id] = ArtifactRevisionRef(
            company_id=artifact.company_id,
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.artifact_revision_id,
            revision=artifact.revision,
            sha256=artifact.sha256,
            byte_length=artifact.byte_length,
        )
    return tuple(result[key] for key in sorted(result))
