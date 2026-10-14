"""Native subject resource plus complete current contributor closure, without blob/network I/O."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.operating_report_resources import report_resources
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


async def qualify_native_inputs(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    services: NativeFactServices,
    resources: tuple[UUID, ...],
    references: tuple[ArtifactRevisionRef, ...],
) -> tuple[tuple[UUID, ...], tuple[datetime, ...]]:
    """Complete current artifact/source/READ closure and fresh deadline capture are mandatory."""
    direct = tuple(sorted(set(resources)))
    if not 1 <= len(direct) <= 32 or len(references) > 33:
        raise BrainDeniedError("Native event input scope exceeds its bound")
    for reference in references:
        await services.artifacts.revalidate_artifact_reference(
            session, control, scope, identity, reference, await db_now(session)
        )
    if references:
        await services.freshness.revalidate_references(
            session, scope, references, await db_now(session)
        )
    required, _, heads = await report_resources(session, scope, direct, references)
    grants = await require_resources(session, scope, required, await db_now(session))
    deadlines = tuple(row.expires_at for row in grants if row.expires_at is not None) + tuple(
        row.fresh_until for row in heads if row.fresh_until is not None
    )
    now = await db_now(session)
    if any(value <= now for value in deadlines):
        raise BrainDeniedError("Native event source/resource deadline expired")
    return required, deadlines
