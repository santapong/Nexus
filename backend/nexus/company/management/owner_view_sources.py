"""Only complete current owner READ plus qualified TTL permits private source-derived fields."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.evidence_models import BrainEvidence
from nexus.company.brain.source_models import BrainArtifactRevision, BrainSourceHead
from nexus.company.brain.sources import ArtifactRevisionRef, EvidenceRef
from nexus.company.management.acceptance_provenance import reference_sources
from nexus.company.management.control_support import db_clock
from nexus.company.management.plan_support import PlanSourceFreshness
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True)
class OwnerViewSources:
    artifacts: BoundedArtifactReader
    freshness: PlanSourceFreshness


@dataclass(frozen=True)
class SourceDisclosure:
    """Internal expiry fence; hidden-source metadata never crosses the view boundary."""

    valid_until: datetime | None

    def permits(self, now: datetime) -> bool:
        return self.valid_until is None or self.valid_until > now


def owner_brain_scope(
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
) -> BrainReadScope:
    return BrainReadScope(
        company_id=scope.company_id,
        workspace_id=identity.workspace_id,
        principal_id=scope.principal_id,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
    )


async def evidence_artifacts(
    session: AsyncSession,
    scope: CompanyControlScope,
    references: tuple[EvidenceRef, ...],
) -> tuple[ArtifactRevisionRef, ...] | None:
    if len(references) > 32 or any(row.company_id != scope.company_id for row in references):
        return None
    values: dict[object, ArtifactRevisionRef] = {}
    for reference in references:
        evidence = await session.get(BrainEvidence, (scope.company_id, reference.evidence_id))
        artifact = (
            await session.get(
                BrainArtifactRevision, (scope.company_id, evidence.artifact_revision_id)
            )
            if evidence is not None
            else None
        )
        if artifact is None:
            return None
        value = ArtifactRevisionRef(
            company_id=artifact.company_id,
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.artifact_revision_id,
            revision=artifact.revision,
            sha256=artifact.sha256,
            byte_length=artifact.byte_length,
        )
        values[value.artifact_revision_id] = value
    return tuple(values.values())


async def source_disclosure(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    sources: OwnerViewSources | None,
    references: tuple[ArtifactRevisionRef, ...],
) -> SourceDisclosure | None:
    if not references:
        return SourceDisclosure(None)
    if sources is None:
        return None
    brain = owner_brain_scope(scope, identity)
    try:
        for reference in references:
            await sources.artifacts.revalidate_artifact_reference(
                session, control, brain, identity, reference, await db_clock(session)
            )
        await sources.freshness.revalidate_references(
            session, brain, references, await db_clock(session)
        )
        ids, resources = await reference_sources(session, brain, references)
        grants = await require_resources(session, brain, resources, await db_clock(session))
        expiries = [row.expires_at for row in grants if row.expires_at is not None]
        observed = (
            await session.scalars(
                select(BrainSourceHead.fresh_until).where(
                    BrainSourceHead.company_id == scope.company_id,
                    BrainSourceHead.source_id.in_(ids),
                    BrainSourceHead.fresh_until.is_not(None),
                )
            )
        ).all()
        expiries.extend(value for value in observed if value is not None)
        result = SourceDisclosure(min(expiries) if expiries else None)
        return result if result.permits(await db_clock(session)) else None
    except ValueError:
        return None
