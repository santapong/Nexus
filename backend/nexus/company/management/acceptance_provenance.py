"""Bounded DB-only complete reference provenance for registered freshness qualification."""

import hashlib
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.models import (
    BrainArtifactRevision,
    BrainDerivationEvidence,
    BrainDerivationSource,
    BrainEvidence,
    BrainSourceRevision,
)
from nexus.company.brain.retrieval_records import contributors, heads
from nexus.company.brain.retrieval_sql import eligible_sources
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.execution.runtime_support import db_now


async def reference_sources(
    session: AsyncSession, scope: BrainReadScope, references: tuple[ArtifactRevisionRef, ...]
) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
    require_acceptance(session.in_transaction() and 0 < len(references) <= 33)
    require_acceptance(
        len({row.artifact_revision_id for row in references}) == len(references)
        and sum(row.byte_length for row in references) <= 8_650_752
    )
    source_ids: set[UUID] = set()
    resource_ids: set[UUID] = set()
    for reference in references:
        artifact = await exact_artifact(session, scope, reference)
        roots = await artifact_roots(session, scope, artifact)
        require_acceptance(0 < len(roots) <= 32)
        allowed = set(
            (
                await session.scalars(
                    eligible_sources(scope, await db_now(session)).where(
                        BrainSourceRevision.source_revision_id.in_(roots)
                    )
                )
            ).all()
        )
        require_acceptance(roots == allowed)
        resource_ids.add(artifact.resource_id)
        for root in sorted(roots):
            refs, resources, _ = await contributors(session, scope, root)
            current = await heads(session, scope, refs)
            by_source = {row.source_id: row.current for row in current}
            require_acceptance(all(by_source[row.source_id] == row for row in refs))
            source_ids.update(row.source_id for row in refs)
            resource_ids.update(resources)
    require_acceptance(len(source_ids) <= 64 and len(resource_ids) <= 32)
    return tuple(sorted(source_ids)), tuple(sorted(resource_ids))


async def exact_artifact(
    session: AsyncSession, scope: BrainReadScope, reference: ArtifactRevisionRef
) -> BrainArtifactRevision:
    require_acceptance(reference.company_id == scope.company_id)
    artifact = await session.get(
        BrainArtifactRevision, (scope.company_id, reference.artifact_revision_id)
    )
    require_acceptance(artifact is not None)
    assert artifact is not None
    actual = ArtifactRevisionRef(
        company_id=artifact.company_id,
        artifact_id=artifact.artifact_id,
        artifact_revision_id=artifact.artifact_revision_id,
        revision=artifact.revision,
        sha256=artifact.sha256,
        byte_length=artifact.byte_length,
    )
    raw = artifact.raw_text.encode()
    require_acceptance(
        actual == reference
        and len(raw) == reference.byte_length
        and hashlib.sha256(raw).hexdigest() == reference.sha256
    )
    return artifact


async def artifact_roots(
    session: AsyncSession, scope: BrainReadScope, artifact: BrainArtifactRevision
) -> set[UUID]:
    roots = set(
        (
            await session.scalars(
                select(BrainSourceRevision.source_revision_id).where(
                    BrainSourceRevision.company_id == scope.company_id,
                    BrainSourceRevision.artifact_revision_id == artifact.artifact_revision_id,
                )
            )
        ).all()
    )
    if artifact.derivation_id is None:
        return roots
    roots.update(
        (
            await session.scalars(
                select(BrainDerivationSource.source_revision_id).where(
                    BrainDerivationSource.company_id == scope.company_id,
                    BrainDerivationSource.derivation_id == artifact.derivation_id,
                )
            )
        ).all()
    )
    roots.update(
        (
            await session.scalars(
                select(BrainEvidence.source_revision_id)
                .join(
                    BrainDerivationEvidence,
                    (BrainDerivationEvidence.company_id == BrainEvidence.company_id)
                    & (BrainDerivationEvidence.evidence_id == BrainEvidence.evidence_id),
                )
                .where(
                    BrainEvidence.company_id == scope.company_id,
                    BrainDerivationEvidence.derivation_id == artifact.derivation_id,
                )
            )
        ).all()
    )
    return roots
