"""Exact native artifact/source/resource input manifests for deterministic report outputs."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.artifact_input_support import artifact_input_closure
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.models import BrainArtifactRevision, BrainSource, BrainSourceRevision
from nexus.company.brain.sources import ArtifactRevisionRef, EvidenceRef, SourceRevisionRef
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_provenance import artifact_roots, exact_artifact
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.core.llm.company_registry import DataClassification

CLASSIFICATIONS: tuple[DataClassification, ...] = (
    "public",
    "internal",
    "confidential",
    "restricted",
)


async def native_manifest(
    session: AsyncSession,
    scope: BrainReadScope,
    artifacts: tuple[ArtifactRevisionRef, ...],
    source_refs: tuple[SourceRevisionRef, ...],
    evidence: tuple[EvidenceRef, ...],
    required_resources: tuple[UUID, ...],
) -> tuple[GeneratedArtifactInputs, DataClassification]:
    """Keep every immutable parent and private contributor, with strongest native class."""
    references = {row.artifact_revision_id: row for row in artifacts}
    for ref in source_refs:
        native = await session.get(BrainSourceRevision, (scope.company_id, ref.source_revision_id))
        require_acceptance(
            native is not None
            and native.source_id == ref.source_id
            and native.revision == ref.revision
        )
        assert native is not None
        artifact = await session.get(
            BrainArtifactRevision, (scope.company_id, native.artifact_revision_id)
        )
        require_acceptance(artifact is not None)
        assert artifact is not None
        references[artifact.artifact_revision_id] = artifact_reference(artifact)
    require_acceptance(0 < len(references) <= 33)
    closure = await artifact_input_closure(session, scope, tuple(sorted(references)))
    resources = set(required_resources) | set(closure.resource_ids)
    revisions = {row.source_revision_id for row in source_refs}
    classes: list[DataClassification] = ["internal", *closure.classifications]
    for key in closure.artifact_revision_ids:
        artifact = await session.get(BrainArtifactRevision, (scope.company_id, key))
        require_acceptance(artifact is not None)
        assert artifact is not None
        reference = artifact_reference(artifact)
        await exact_artifact(session, scope, reference)
        references[key] = reference
        revisions.update(await artifact_roots(session, scope, artifact))
    contributors = await source_manifest(session, scope, revisions, resources, classes)
    manifest = GeneratedArtifactInputs(
        company_id=scope.company_id,
        artifacts=tuple(references[key] for key in sorted(references)),
        contributors=contributors,
        evidence=evidence,
        required_resource_ids=tuple(sorted(resources)),
    )
    return manifest, max(classes, key=CLASSIFICATIONS.index)


async def source_manifest(
    session: AsyncSession,
    scope: BrainReadScope,
    revisions: set[UUID],
    resources: set[UUID],
    classes: list[DataClassification],
) -> tuple[SourceRevisionRef, ...]:
    """Resolve actual native contributors, never a caller's asserted source class."""
    require_acceptance(0 < len(revisions) <= 32)
    result: list[SourceRevisionRef] = []
    for key in sorted(revisions):
        revision = await session.get(BrainSourceRevision, (scope.company_id, key))
        require_acceptance(revision is not None)
        assert revision is not None
        source = await session.get(BrainSource, (scope.company_id, revision.source_id))
        require_acceptance(source is not None and source.data_classification in CLASSIFICATIONS)
        assert source is not None
        resources.add(source.resource_id)
        classes.append(
            next(value for value in CLASSIFICATIONS if value == source.data_classification)
        )
        result.append(
            SourceRevisionRef(
                company_id=scope.company_id,
                source_id=revision.source_id,
                source_revision_id=key,
                revision=revision.revision,
            )
        )
    return tuple(result)


def artifact_reference(artifact: BrainArtifactRevision) -> ArtifactRevisionRef:
    """Describe immutable native metadata; the caller still validates its actual authority."""
    return ArtifactRevisionRef(
        company_id=artifact.company_id,
        artifact_id=artifact.artifact_id,
        artifact_revision_id=artifact.artifact_revision_id,
        revision=artifact.revision,
        sha256=artifact.sha256,
        byte_length=artifact.byte_length,
    )
