"""Exact selected native receipt/acceptance/invoice plus baseline source artifact input roots."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.operating_report_capture import selected_states
from nexus.company.management.operating_report_contracts import SavedOperatingReport
from nexus.company.management.operating_report_read import current_source_artifacts
from nexus.harness.journal_models import CompanyControl


async def author_input_references(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    record: SavedOperatingReport,
    artifacts: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
) -> tuple[ArtifactRevisionRef, ...]:
    _, selected = await selected_states(
        session,
        control,
        scope,
        identity,
        record.selection,
        artifacts,
        freshness,
    )
    baseline = await current_source_artifacts(session, scope, record.data, None)
    references: dict[UUID, ArtifactRevisionRef] = {}
    for value in (*selected, *baseline):
        previous = references.get(value.artifact_revision_id)
        require_acceptance(previous is None or previous == value)
        references[value.artifact_revision_id] = value
    result = tuple(references[key] for key in sorted(references))
    require_acceptance(
        0 < len(result) <= 33 and sum(row.byte_length for row in result) <= 8_650_752
    )
    return result
