"""Exact obsolete-history roots retain complete current READ; no current-head equality claim."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.operating_report_resources import report_resources


async def historical_reference_sources(
    session: AsyncSession,
    scope: BrainReadScope,
    references: tuple[ArtifactRevisionRef, ...],
) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
    """Reuse exact ancestor/eligible-source closure and actual current contributor grants."""
    require_acceptance(session.in_transaction() and 0 < len(references) <= 33)
    require_acceptance(
        len({row.artifact_revision_id for row in references}) == len(references)
        and sum(row.byte_length for row in references) <= 8_650_752
        and all(row.company_id == scope.company_id for row in references)
    )
    resources, _, heads = await report_resources(session, scope, (), references)
    ids = tuple(sorted({row.source_id for row in heads}))
    require_acceptance(0 < len(ids) <= 64 and 0 < len(resources) <= 32)
    return ids, resources
