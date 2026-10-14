"""Exact historical registered charter scope and native current source/output input roots."""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.brain.native_fact_work import actual_work
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.source_models import (
    BrainArtifactRevision,
    BrainSource,
    BrainSourceHead,
    BrainSourceRevision,
)
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.control_support import charter_record
from nexus.company.management.governance_models import ManagementCharterRevision
from nexus.company.management.plan_models import ManagementPlanRevision, ManagementPlanTask
from nexus.company.management.plans import RunBinding
from nexus.company.management.report_input_contracts import native_author
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import db_now


async def work_resources(
    session: AsyncSession, scope: BrainReadScope, task_id: UUID, services: NativeFactServices
) -> tuple[UUID, ...]:
    """Revoked work still retains its actual immutable charter; absence never means public."""
    work = await actual_work(session, scope.company_id, task_id)
    row = await session.scalar(
        select(ManagementPlanTask)
        .join(
            ManagementPlanRevision,
            (ManagementPlanRevision.company_id == ManagementPlanTask.company_id)
            & (ManagementPlanRevision.plan_revision_id == ManagementPlanTask.plan_revision_id),
        )
        .where(
            ManagementPlanTask.company_id == scope.company_id,
            ManagementPlanTask.task_id == task_id,
            ManagementPlanTask.run_id == work.run_id,
            ManagementPlanTask.work_sha256 == work.registration_hash,
        )
        .order_by(
            ManagementPlanRevision.recorded_at.desc(),
            ManagementPlanRevision.plan_revision_id.desc(),
        )
        .limit(1)
    )
    if row is None or RunBinding.model_validate_json(row.binding_json) != native_author(work)[0]:
        raise BrainDeniedError("Native event registered plan/charter binding is unavailable")
    stored = await session.get(
        ManagementCharterRevision, (scope.company_id, row.charter_revision_id)
    )
    if stored is None or stored.department_id != row.department_id:
        raise BrainDeniedError("Native event historical charter is unavailable")
    charter = await charter_record(session, stored)
    mapping = {item.symbol: item.resource for item in services.catalog.resources}
    if not set(charter.charter.resource_scopes) <= mapping.keys():
        raise BrainDeniedError("Native event resource mapping is unavailable")
    return tuple(sorted({mapping[key].resource_id for key in charter.charter.resource_scopes}))


def artifact_query() -> Select[tuple[UUID, UUID, UUID, str, str, int]]:
    """Native references need metadata only; protected raw_text is not selected here."""
    return select(
        BrainArtifactRevision.company_id,
        BrainArtifactRevision.artifact_id,
        BrainArtifactRevision.artifact_revision_id,
        BrainArtifactRevision.revision,
        BrainArtifactRevision.sha256,
        BrainArtifactRevision.byte_length,
    )


async def source_artifact_reference(
    session: AsyncSession,
    scope: BrainReadScope,
    artifact_revision_id: UUID,
) -> ArtifactRevisionRef:
    row = (
        (
            await session.execute(
                artifact_query().where(
                    BrainArtifactRevision.company_id == scope.company_id,
                    BrainArtifactRevision.artifact_revision_id == artifact_revision_id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise BrainDeniedError("Native event source artifact metadata is unavailable")
    return ArtifactRevisionRef.model_validate(dict(row))


async def source_references(
    session: AsyncSession, scope: BrainReadScope, resource_ids: tuple[UUID, ...]
) -> tuple[ArtifactRevisionRef, ...]:
    await require_resources(session, scope, resource_ids, await db_now(session))
    sources = tuple(
        (
            await session.scalars(
                select(BrainSource)
                .where(
                    BrainSource.company_id == scope.company_id,
                    BrainSource.resource_id.in_(resource_ids),
                )
                .limit(65)
            )
        ).all()
    )
    if len(sources) > 64:
        raise BrainDeniedError("Native event source scope exceeds its bound")
    references = {}
    for source in sources:
        head = await session.get(BrainSourceHead, (scope.company_id, source.source_id))
        revision = (
            await session.get(BrainSourceRevision, (scope.company_id, head.current_revision_id))
            if head
            else None
        )
        if revision is None or revision.source_id != source.source_id:
            raise BrainDeniedError("Native event source head is unavailable")
        artifact = await source_artifact_reference(session, scope, revision.artifact_revision_id)
        references[artifact.artifact_revision_id] = artifact
    return tuple(references[key] for key in sorted(references))


async def receipt_references(
    session: AsyncSession, scope: BrainReadScope, task_id: UUID
) -> tuple[ArtifactRevisionRef, ...]:
    effects = tuple(
        (
            await session.scalars(
                select(EffectIntent)
                .where(
                    EffectIntent.company_id == scope.company_id,
                    EffectIntent.task_id == task_id,
                    EffectIntent.receipt_json.is_not(None),
                )
                .limit(33)
            )
        ).all()
    )
    if len(effects) > 32:
        raise BrainDeniedError("Native event receipt scope exceeds its bound")
    references = {}
    for effect in effects:
        receipt = ActionReceipt.model_validate_json(effect.receipt_json or "")
        for ref in receipt.artifacts:
            row = (
                (
                    await session.execute(
                        artifact_query().where(
                            BrainArtifactRevision.company_id == scope.company_id,
                            BrainArtifactRevision.artifact_id == ref.artifact_id,
                            BrainArtifactRevision.revision == ref.revision,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["sha256"] != ref.sha256:
                raise BrainDeniedError("Native event receipt artifact is unavailable")
            artifact = ArtifactRevisionRef.model_validate(dict(row))
            references[artifact.artifact_revision_id] = artifact
    return tuple(references[key] for key in sorted(references))
