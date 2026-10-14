"""Bounded immutable artifact ancestry retains all current resource and classification needs."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.artifact_input_models import BrainArtifactInput, BrainArtifactResourceInput
from nexus.company.brain.base import BrainReadScope, ValueContract
from nexus.company.brain.derivation_models import BrainDerivationEvidence, BrainDerivationSource
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.source_models import BrainArtifactRevision, BrainSourceRevision
from nexus.core.llm.company_registry import DataClassification

CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")


class ArtifactInputClosure(ValueContract):
    artifact_revision_ids: tuple[UUID, ...]
    resource_ids: tuple[UUID, ...]
    classifications: tuple[DataClassification, ...]


async def artifact_input_closure(
    session: AsyncSession, scope: BrainReadScope, roots: tuple[UUID, ...]
) -> ArtifactInputClosure:
    """Reject missing/cyclic/deep ancestry; raw bytes remain outside this DB-only helper."""
    if not roots or len(roots) > 33 or len(set(roots)) != len(roots):
        raise BrainDeniedError("Artifact input selection is unavailable")
    resources: set[UUID] = set()
    classes: set[str] = set()
    edges: dict[UUID, tuple[UUID, ...]] = {}
    pending = list(roots)
    while pending:
        key = pending.pop()
        if key in edges:
            continue
        if len(edges) >= 33:
            raise BrainDeniedError("Artifact input ancestry exceeds its bound")
        row = await session.get(BrainArtifactRevision, (scope.company_id, key))
        if row is None:
            raise BrainDeniedError("Artifact input is unavailable")
        resources.add(row.resource_id)
        if row.data_classification is not None:
            if row.data_classification not in CLASSIFICATIONS:
                raise BrainDeniedError("Artifact classification is unavailable")
            classes.add(row.data_classification)
        links = tuple(
            (
                await session.scalars(
                    select(BrainArtifactInput.input_artifact_revision_id).where(
                        BrainArtifactInput.company_id == scope.company_id,
                        BrainArtifactInput.artifact_revision_id == key,
                    )
                )
            ).all()
        )
        extras = (
            await session.scalars(
                select(BrainArtifactResourceInput.resource_id).where(
                    BrainArtifactResourceInput.company_id == scope.company_id,
                    BrainArtifactResourceInput.artifact_revision_id == key,
                )
            )
        ).all()
        resources.update(extras)
        if not links:
            qualified = await session.scalar(
                select(
                    or_(
                        exists(
                            select(BrainSourceRevision.source_revision_id).where(
                                BrainSourceRevision.company_id == scope.company_id,
                                BrainSourceRevision.artifact_revision_id == key,
                            )
                        ),
                        exists(
                            select(BrainDerivationSource.derivation_id).where(
                                BrainDerivationSource.company_id == scope.company_id,
                                BrainDerivationSource.derivation_id == row.derivation_id,
                            )
                        ),
                        exists(
                            select(BrainDerivationEvidence.derivation_id).where(
                                BrainDerivationEvidence.company_id == scope.company_id,
                                BrainDerivationEvidence.derivation_id == row.derivation_id,
                            )
                        ),
                    )
                )
            )
            if not qualified:
                raise BrainDeniedError("Artifact input leaf has no qualified source origin")
        if len(resources) > 32 or len(links) > 32:
            raise BrainDeniedError("Artifact input resources exceed their bound")
        edges[key] = links
        pending.extend(links)
    depths: dict[UUID, int] = {}
    for key in roots:
        _depth(edges, key, frozenset(), depths)
    return ArtifactInputClosure.model_validate(
        {
            "artifact_revision_ids": tuple(sorted(edges)),
            "resource_ids": tuple(sorted(resources)),
            "classifications": tuple(sorted(classes, key=CLASSIFICATIONS.index)),
        }
    )


def _depth(
    edges: dict[UUID, tuple[UUID, ...]], key: UUID, path: frozenset[UUID], depths: dict[UUID, int]
) -> int:
    if key in path:
        raise BrainDeniedError("Artifact input ancestry is cyclic")
    if key in depths:
        return depths[key]
    depth = 1 + max(
        (_depth(edges, parent, path | {key}, depths) for parent in edges[key]), default=0
    )
    if depth > 16:
        raise BrainDeniedError("Artifact input ancestry is too deep")
    depths[key] = depth
    return depth
