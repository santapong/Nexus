"""Complete contributor closure and private recipient intersection before publication."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_models import BrainResourceAccess
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.claims import DerivationRecord
from nexus.company.brain.derivation_models import (
    BrainDerivation,
    BrainDerivationEvidence,
    BrainDerivationSource,
)
from nexus.company.brain.evidence_models import BrainEvidence
from nexus.company.brain.scope_support import BrainConflictError, BrainDeniedError
from nexus.company.brain.source_models import BrainSource, BrainSourceHead, BrainSourceRevision
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.directory_models import DirectoryMembership

_CLASSIFICATION = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


async def validate_derivation(
    session: AsyncSession,
    scope: BrainReadScope,
    value: DerivationRecord,
    artifact: ArtifactRevisionRef,
    resource_id: UUID,
    policy: SourcePolicy,
    now: datetime,
) -> None:
    """No filesystem/model I/O; every input/read recipient is rechecked under the company mutex."""
    if (
        value.company_id != scope.company_id
        or value.artifact != artifact
        or len(set(value.evidence)) != len(value.evidence)
    ):
        raise BrainDeniedError("Derivative provenance is unavailable")
    refs = {ref.source_revision_id: ref for ref in value.contributors}
    for reference in value.evidence:
        evidence = await session.get(
            BrainEvidence, {"company_id": scope.company_id, "evidence_id": reference.evidence_id}
        )
        if evidence is None or evidence.source_revision_id not in refs:
            raise BrainDeniedError("Derivative evidence omits its contributing source")
    resources: set[UUID] = set()
    classification = 0
    for ref in value.contributors:
        row = await session.get(
            BrainSourceRevision,
            {"company_id": scope.company_id, "source_revision_id": ref.source_revision_id},
        )
        if row is None or (row.source_id, row.revision) != (ref.source_id, ref.revision):
            raise BrainDeniedError("Derivative source revision is unavailable")
        classification = max(
            classification, await _closure(session, scope, row, resources, frozenset(), now)
        )
    if (
        len(resources) > 32
        or resource_id in resources
        or _CLASSIFICATION[policy.data_classification] < classification
    ):
        raise BrainDeniedError("Derivative cannot widen input classification or provenance")
    await require_resources(session, scope, tuple(sorted(resources)), now)
    await _recipients(session, scope, resource_id, tuple(sorted(resources)), now)


async def _closure(
    session: AsyncSession,
    scope: BrainReadScope,
    row: BrainSourceRevision,
    resources: set[UUID],
    ancestry: frozenset[UUID],
    now: datetime,
) -> int:
    if len(ancestry) >= 16 or row.source_revision_id in ancestry:
        raise BrainDeniedError("Derivative provenance depth or cycle is invalid")
    source = await session.get(
        BrainSource, {"company_id": scope.company_id, "source_id": row.source_id}
    )
    head = await session.get(
        BrainSourceHead, {"company_id": scope.company_id, "source_id": row.source_id}
    )
    if source is None or head is None:
        raise BrainDeniedError("Derivative provenance is unavailable")
    if (
        head.current_revision_id != row.source_revision_id
        or head.availability != "available"
        or (head.fresh_until is not None and head.fresh_until <= now)
    ):
        raise BrainConflictError("Derivative source changed or is unavailable")
    resources.add(source.resource_id)
    if len(resources) > 32:
        raise BrainDeniedError("Derivative resource closure exceeds its bound")
    strongest = _CLASSIFICATION[source.data_classification]
    if row.derivation_id is None:
        return strongest
    edges = (
        await session.scalars(
            select(BrainDerivationSource).where(
                BrainDerivationSource.company_id == scope.company_id,
                BrainDerivationSource.derivation_id == row.derivation_id,
            )
        )
    ).all()
    if not edges:
        raise BrainDeniedError("Derivative lacks its complete source manifest")
    for edge in edges:
        child = await session.get(
            BrainSourceRevision,
            {"company_id": scope.company_id, "source_revision_id": edge.source_revision_id},
        )
        if child is None:
            raise BrainDeniedError("Derivative contributor is unavailable")
        strongest = max(
            strongest,
            await _closure(
                session, scope, child, resources, ancestry | {row.source_revision_id}, now
            ),
        )
    return strongest


async def _recipients(
    session: AsyncSession,
    scope: BrainReadScope,
    resource_id: UUID,
    contributors: tuple[UUID, ...],
    now: datetime,
) -> None:
    rows = (
        await session.scalars(
            select(BrainResourceAccess).where(
                BrainResourceAccess.company_id == scope.company_id,
                BrainResourceAccess.resource_id == resource_id,
                BrainResourceAccess.active.is_(True),
                or_(BrainResourceAccess.expires_at.is_(None), BrainResourceAccess.expires_at > now),
            )
        )
    ).all()
    if not rows:
        raise BrainDeniedError("Derivative has no explicit current readers")
    for grant in rows:
        member = await session.get(DirectoryMembership, (scope.company_id, grant.principal_id))
        if member is None or not member.principal_active or not member.membership_active:
            raise BrainDeniedError("Derivative recipient is unavailable")
        recipient = scope.model_copy(update={"principal_id": grant.principal_id})
        await require_resources(session, recipient, contributors, now)


async def save_derivation(session: AsyncSession, value: DerivationRecord) -> None:
    """Deferred artifact FK commits the immutable derivative and artifact together."""
    existing = await session.get(
        BrainDerivation, {"company_id": value.company_id, "derivation_id": value.derivation_id}
    )
    if existing is not None:
        raise BrainConflictError("Derivative identity is already registered")
    session.add(
        BrainDerivation(
            company_id=value.company_id,
            derivation_id=value.derivation_id,
            artifact_revision_id=value.artifact.artifact_revision_id,
            kind=value.kind,
            recipe_version=value.recipe_version,
            model_recipe=value.model_recipe,
            prompt_sha256=value.prompt_sha256,
            recorded_at=value.recorded_at,
        )
    )
    await session.flush()
    for source in value.contributors:
        session.add(
            BrainDerivationSource(
                company_id=value.company_id,
                derivation_id=value.derivation_id,
                source_revision_id=source.source_revision_id,
            )
        )
    for evidence in value.evidence:
        session.add(
            BrainDerivationEvidence(
                company_id=value.company_id,
                derivation_id=value.derivation_id,
                evidence_id=evidence.evidence_id,
            )
        )
