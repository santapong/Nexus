"""Server catalog resources and complete native artifact provenance precede parameter disclosure."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.source_models import (
    BrainArtifactRevision,
    BrainSource,
    BrainSourceHead,
    BrainSourceRevision,
)
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.control_support import charter_record, db_clock
from nexus.company.management.governance_models import ManagementCharterRevision
from nexus.company.management.plan_support import (
    CurrentPlanBinding,
    PlanAdmissionCatalog,
    validate_plan_action,
)
from nexus.company.management.transactions import ManagementDeniedError


async def review_artifacts(
    session: AsyncSession,
    binding: CurrentPlanBinding,
    proposal: ActionProposal,
    catalog: PlanAdmissionCatalog,
) -> tuple[tuple[ArtifactRevisionRef, ...], tuple[UUID, ...]]:
    row = await session.get(
        ManagementCharterRevision, (binding.company_id, binding.child.charter.revision_id)
    )
    if row is None:
        raise ManagementDeniedError("Action review resources are unavailable")
    charter = await charter_record(session, row)
    validate_plan_action(
        catalog,
        binding.child,
        charter,
        proposal,
        "model_requests" if proposal.tool == "model.request.v1" else "tool_attempts",
        await db_clock(session),
    )
    symbols = (
        set(charter.charter.resource_scopes)
        | {proposal.resource}
        | {value.resource for value in proposal.preconditions}
    )
    references = {value.symbol: value.resource for value in catalog.resources}
    if not symbols or not symbols <= references.keys():
        raise ManagementDeniedError("Action review resources are not configured")
    selected = []
    for symbol in sorted(symbols):
        target = (
            proposal.tool in {"company.report.write.v1", "company.report.check.v1"}
            and symbol == proposal.resource
            and not any(value.resource == symbol for value in proposal.preconditions)
        )
        artifact = await current_artifact(
            session, references[symbol].resource_id, binding, empty_target=target
        )
        if artifact is None:
            continue
        if any(
            value.resource == symbol and value.revision != artifact.revision
            for value in proposal.preconditions
        ):
            raise ManagementDeniedError("Action review resource revision changed")
        selected.append(artifact)
    return (
        tuple({value.artifact_revision_id: value for value in selected}.values()),
        tuple(sorted({references[symbol].resource_id for symbol in symbols})),
    )


async def current_artifact(
    session: AsyncSession,
    resource_id: UUID,
    binding: CurrentPlanBinding,
    *,
    empty_target: bool = False,
) -> ArtifactRevisionRef | None:
    resource = await session.get(BrainResource, (binding.company_id, resource_id))
    if resource is None or not resource.active or resource.kind not in {"source", "artifact"}:
        raise ManagementDeniedError("Action review resource is unavailable")
    if resource.kind == "artifact":
        rows = tuple(
            (
                await session.scalars(
                    select(BrainArtifactRevision)
                    .where(
                        BrainArtifactRevision.company_id == binding.company_id,
                        BrainArtifactRevision.resource_id == resource_id,
                    )
                    .limit(2)
                )
            ).all()
        )
        if not rows and empty_target:
            return None
        if len(rows) != 1:
            raise ManagementDeniedError("Action review needs one exact current artifact")
        return artifact_reference(rows[0])
    rows = await source_artifacts(session, binding.company_id, resource_id)
    if len(rows) != 1:
        raise ManagementDeniedError("Action review needs one exact current artifact")
    return artifact_reference(rows[0])


async def source_artifacts(
    session: AsyncSession, company_id: UUID, resource_id: UUID
) -> tuple[BrainArtifactRevision, ...]:
    query = (
        select(BrainArtifactRevision)
        .join(
            BrainSourceRevision,
            (BrainSourceRevision.company_id == BrainArtifactRevision.company_id)
            & (
                BrainSourceRevision.artifact_revision_id
                == BrainArtifactRevision.artifact_revision_id
            ),
        )
        .join(
            BrainSourceHead,
            (BrainSourceHead.company_id == BrainSourceRevision.company_id)
            & (BrainSourceHead.current_revision_id == BrainSourceRevision.source_revision_id),
        )
        .join(
            BrainSource,
            (BrainSource.company_id == BrainSourceRevision.company_id)
            & (BrainSource.source_id == BrainSourceRevision.source_id),
        )
        .where(
            BrainArtifactRevision.company_id == company_id,
            BrainSource.resource_id == resource_id,
            BrainSourceHead.availability == "available",
        )
        .distinct()
        .limit(2)
    )
    return tuple((await session.scalars(query)).all())


def artifact_reference(row: BrainArtifactRevision) -> ArtifactRevisionRef:
    return ArtifactRevisionRef(
        company_id=row.company_id,
        artifact_id=row.artifact_id,
        artifact_revision_id=row.artifact_revision_id,
        revision=row.revision,
        sha256=row.sha256,
        byte_length=row.byte_length,
    )
