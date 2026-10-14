"""Complete native input closure and every recipient intersection under CompanyControl."""

from datetime import datetime
from uuid import UUID

from pydantic import Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.artifact_input_support import CLASSIFICATIONS, artifact_input_closure
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope, ValueContract
from nexus.company.brain.retrieval_records import contributors, heads
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.source_models import (
    BrainArtifactRevision,
    BrainSource,
    BrainSourceHead,
    BrainSourceRevision,
)
from nexus.company.brain.sources import ArtifactRevisionRef, SourceHead, SourceRevisionRef
from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.acceptance_provenance import artifact_roots
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactPayload,
    GeneratedArtifactRule,
)
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


class GeneratedProtection(ValueContract):
    """Observed timed grants/heads, including all distinct recipients; not a permit."""

    grants: tuple[ResourceGeneration, ...] = Field(max_length=1056)
    heads: tuple[SourceHead, ...] = Field(max_length=32)

    def require_time(self, now: datetime) -> None:
        if any(row.expires_at is not None and row.expires_at <= now for row in self.grants) or any(
            row.availability != "available"
            or (row.fresh_until is not None and row.fresh_until <= now)
            for row in self.heads
        ):
            raise BrainDeniedError("Native artifact input/recipient permission or source expired")


async def recipients(
    session: AsyncSession,
    scope: BrainReadScope,
    target: UUID,
    resources: tuple[UUID, ...],
    now: datetime,
) -> tuple[ResourceGeneration, ...]:
    """Do not drop a prepared reader merely because its grant expires during publication."""
    rows = (
        await session.scalars(
            select(BrainResourceAccess).where(
                BrainResourceAccess.company_id == scope.company_id,
                BrainResourceAccess.resource_id == target,
                BrainResourceAccess.active.is_(True),
                or_(BrainResourceAccess.expires_at.is_(None), BrainResourceAccess.expires_at > now),
            )
        )
    ).all()
    if not 1 <= len(rows) <= 32:
        raise BrainDeniedError("Native artifact target has no bounded actual current readership")
    grants: list[ResourceGeneration] = []
    for row in rows:
        member = await session.get(DirectoryMembership, (scope.company_id, row.principal_id))
        if member is None or not member.principal_active or not member.membership_active:
            raise BrainDeniedError("Native artifact recipient is unavailable")
        grants.extend(
            await require_resources(
                session, scope.model_copy(update={"principal_id": row.principal_id}), resources, now
            )
        )
    return tuple(grants)


async def source_inputs(
    session: AsyncSession, scope: BrainReadScope, prepared: GeneratedArtifactPayload
) -> tuple[
    tuple[SourceRevisionRef, ...],
    tuple[UUID, ...],
    tuple[ArtifactRevisionRef, ...],
    tuple[str, ...],
]:
    """Resolve every native input path and declared source-resource origin; reject omissions."""
    # Complete source and artifact paths stay in this >50-line bounded closure.
    refs: dict[UUID, SourceRevisionRef] = {}
    resources: set[UUID] = set()
    classes: list[str] = []
    roots = set()
    if prepared.inputs.artifacts:
        lineage = await artifact_input_closure(
            session, scope, tuple(row.artifact_revision_id for row in prepared.inputs.artifacts)
        )
        resources.update(lineage.resource_ids)
        classes.extend(lineage.classifications)
        for key in lineage.artifact_revision_ids:
            artifact = await session.get(BrainArtifactRevision, (scope.company_id, key))
            if artifact is None:
                raise BrainDeniedError("Native input artifact is unavailable")
            roots.update(await artifact_roots(session, scope, artifact))
    for ref in prepared.inputs.contributors:
        row = await session.get(BrainSourceRevision, (scope.company_id, ref.source_revision_id))
        if row is None or (row.source_id, row.revision) != (ref.source_id, ref.revision):
            raise BrainDeniedError("Exact generated source contributor is unavailable")
        roots.add(ref.source_revision_id)
    source_rows = (
        await session.scalars(
            select(BrainSource).where(
                BrainSource.company_id == scope.company_id,
                BrainSource.resource_id.in_(prepared.inputs.required_resource_ids),
            )
        )
    ).all()
    if len(source_rows) > 32:
        raise BrainDeniedError("Native generated source resources exceed their bound")
    for source in source_rows:
        head = await session.get(BrainSourceHead, (scope.company_id, source.source_id))
        if head is None:
            raise BrainDeniedError("Required source resource has no current origin")
        roots.add(head.current_revision_id)
    for key in sorted(roots):
        expanded, required, sources = await contributors(session, scope, key)
        refs.update({row.source_revision_id: row for row in expanded})
        resources.update(required)
        classes.extend(row.data_classification for row in sources)
    actual = tuple(refs[key] for key in sorted(refs))
    if (
        not actual
        or len(actual) > 32
        or {row.source_revision_id: row for row in actual}
        != {row.source_revision_id: row for row in prepared.inputs.contributors}
        or not resources <= set(prepared.inputs.required_resource_ids)
    ):
        raise BrainDeniedError(
            "Generated input manifest omits its complete native source/resource closure"
        )
    native_refs = {row.artifact_revision_id: row for row in prepared.inputs.artifacts}
    for ref in actual:
        revision = await session.get(
            BrainSourceRevision, (scope.company_id, ref.source_revision_id)
        )
        assert revision is not None
        artifact = await session.get(
            BrainArtifactRevision, (scope.company_id, revision.artifact_revision_id)
        )
        if artifact is None:
            raise BrainDeniedError("Generated source artifact is unavailable")
        native_refs[artifact.artifact_revision_id] = ArtifactRevisionRef(
            company_id=scope.company_id,
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.artifact_revision_id,
            revision=artifact.revision,
            sha256=artifact.sha256,
            byte_length=artifact.byte_length,
        )
    return (
        actual,
        tuple(sorted(resources)),
        tuple(native_refs[key] for key in sorted(native_refs)),
        tuple(classes),
    )


async def protect_inputs(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    prepared: GeneratedArtifactPayload,
    rule: GeneratedArtifactRule,
    reader: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
) -> GeneratedProtection:
    """Current signed reader/complete origin/qualified policy and full recipient intersection."""
    target = await session.get(BrainResource, (scope.company_id, rule.target.resource_id))
    if target is None or target.kind != "artifact" or not target.active:
        raise BrainDeniedError(
            "Generated target is not a current owner-provisioned artifact resource"
        )
    refs, _, artifacts, classes = await source_inputs(session, scope, prepared)
    for artifact in artifacts:
        await reader.revalidate_artifact_reference(
            session, control, scope, identity, artifact, await db_now(session)
        )
    await freshness.revalidate_references(session, scope, artifacts, await db_now(session))
    if any(
        CLASSIFICATIONS.index(value) > CLASSIFICATIONS.index(prepared.data_classification)
        for value in classes
    ):
        raise BrainDeniedError("Generated artifact cannot downgrade actual input classification")
    current = await heads(session, scope, refs)
    if {row.current for row in current} != set(refs):
        raise BrainDeniedError("Generated contributor head changed")
    resources = tuple(
        sorted(set(prepared.inputs.required_resource_ids) | {rule.target.resource_id})
    )
    now = await db_now(session)
    writer = await require_resources(session, scope, resources, now)
    audience = await recipients(session, scope, rule.target.resource_id, resources, now)
    result = GeneratedProtection(grants=(*writer, *audience), heads=current)
    result.require_time(await db_now(session))
    return result
