"""Explicit obsolete-only historical references with full current source/READ/final-time closure."""

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


async def qualify_obsolete_native_inputs(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    services: NativeFactServices,
    resources: tuple[UUID, ...],
    references: tuple[ArtifactRevisionRef, ...],
) -> tuple[tuple[UUID, ...], tuple[datetime, ...]]:
    """Historical age never replaces exact immutable bytes, current policy or contributor access."""
    direct = tuple(sorted(set(resources)))
    if (
        not session.in_transaction()
        or control.company_id != scope.company_id
        or services.catalog.company_id != scope.company_id
        or not 1 <= len(direct) <= 32
        or len(references) > 33
        or len({row.artifact_revision_id for row in references}) != len(references)
        or sum(row.byte_length for row in references) > 8_650_752
    ):
        raise BrainDeniedError("Native obsolete input scope is unavailable")
    deadlines: set[datetime] = set()
    for reference in references:
        qualified = await services.artifacts.revalidate_historical_artifact_reference(
            session, control, scope, identity, reference, await db_now(session)
        )
        deadlines.update(qualified)
    if references:
        deadlines.update(
            await services.freshness.revalidate_historical_references(
                session,
                scope,
                references,
                await db_now(session),
            )
        )
    required, _, heads = await report_resources(session, scope, direct, references)
    grants = await require_resources(session, scope, required, await db_now(session))
    deadlines.update(row.expires_at for row in grants if row.expires_at is not None)
    deadlines.update(row.fresh_until for row in heads if row.fresh_until is not None)
    if any(row.availability != "available" for row in heads):
        raise BrainDeniedError("Native obsolete current source is unavailable")
    final = await db_now(session)
    if any(value <= final for value in deadlines):
        raise BrainDeniedError("Native obsolete input protection expired")
    return required, tuple(sorted(deadlines))
