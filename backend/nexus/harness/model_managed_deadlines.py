"""Exact managed plan grant/source and actor-readable proof deadlines at the final model clock."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_models import BrainResource, BrainResourceAccess
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.native_fact_inputs import source_references
from nexus.company.brain.source_models import BrainSource, BrainSourceHead
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.model_observations import ModelEligibilityObservation
from nexus.company.management.operating_report_resources import report_resources
from nexus.company.management.plan_support import PlanAdmissionCatalog, validate_plan_profile
from nexus.company.management.plans import ChildAllocation
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl
from nexus.harness.model_managed_inputs import ManagedModelInputs, load_managed_model_inputs


@dataclass(frozen=True, slots=True)
class ManagedModelDeadlineSnapshot:
    deadlines: tuple[datetime, ...]
    children: tuple[ChildAllocation, ...]


def require_managed_gateway_configuration(
    management: ManagementExecutionServices | None,
    registry: ModelRegistry,
    observations: tuple[ModelEligibilityObservation, ...],
) -> None:
    if management is not None and (
        management.catalog.models != registry
        or management.catalog.model_observations != observations
    ):
        raise ValueError("Managed model registry/observations differ from gateway configuration")


def require_managed_model_time(
    snapshot: ManagedModelDeadlineSnapshot,
    catalog: PlanAdmissionCatalog,
    now: datetime,
) -> None:
    """Pure last-clock check retains ANY current profile semantics; dates grant no permission."""
    if any(value <= now for value in snapshot.deadlines):
        raise ValueError("Managed model source/resource qualification expired")
    for child in snapshot.children:
        validate_plan_profile(catalog, child, now)


async def managed_model_deadlines(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    identity: VerifiedIdentity,
    management: ManagementExecutionServices,
) -> ManagedModelDeadlineSnapshot:
    actual = await load_managed_model_inputs(session, control, work, identity, management)
    if actual is None:
        return ManagedModelDeadlineSnapshot((), ())
    scope = BrainReadScope(
        company_id=work.company_id,
        workspace_id=work.workspace_id,
        principal_id=identity.principal_id,
        operation_id=uuid5(work.task_id, "model-pre-sdk-deadlines"),
        trace_id=work.trace_id,
        task_id=work.task_id,
        task_trace_id=work.trace_id,
        actor_id=work.actor_id,
    )
    references = _references(
        (*actual.artifacts, *await source_references(session, scope, actual.own_resource_ids))
    )
    for reference in references:
        await management.artifacts.revalidate_artifact_reference(
            session, control, scope, identity, reference, await db_now(session)
        )
    if references:
        await management.freshness.revalidate_references(
            session, scope, references, await db_now(session)
        )
    required, _, heads = await report_resources(session, scope, actual.own_resource_ids, references)
    grants = await require_resources(session, scope, required, await db_now(session))
    deadlines = {row.expires_at for row in grants if row.expires_at is not None}
    deadlines.update(row.fresh_until for row in heads if row.fresh_until is not None)
    deadlines.update(await capture_plan_deadlines(session, work, actual))
    return ManagedModelDeadlineSnapshot(tuple(sorted(deadlines)), actual.payload.children)


def _references(values: tuple[ArtifactRevisionRef, ...]) -> tuple[ArtifactRevisionRef, ...]:
    result: dict[UUID, ArtifactRevisionRef] = {}
    for ref in values:
        previous = result.get(ref.artifact_revision_id)
        if previous is not None and previous != ref:
            raise ValueError("Managed model source artifact references conflict")
        result[ref.artifact_revision_id] = ref
    rows = tuple(result[key] for key in sorted(result))
    if len(rows) > 33 or sum(row.byte_length for row in rows) > 8_650_752:
        raise ValueError("Managed model source closure exceeds its bound")
    return rows


async def capture_plan_deadlines(
    session: AsyncSession,
    work: ExecutionWork,
    actual: ManagedModelInputs,
) -> tuple[datetime, ...]:
    """Read only exact declared child/charter pairs, never a global actor/resource product."""
    rows = tuple(
        (
            await session.execute(
                select(BrainResource, BrainResourceAccess)
                .join(
                    BrainResourceAccess,
                    (BrainResourceAccess.company_id == BrainResource.company_id)
                    & (BrainResourceAccess.resource_id == BrainResource.resource_id),
                )
                .where(
                    BrainResource.company_id == work.company_id,
                    tuple_(BrainResource.resource_id, BrainResourceAccess.principal_id).in_(
                        actual.grant_pairs
                    ),
                )
                .limit(6401)
            )
        ).all()
    )
    if len(rows) != len(actual.grant_pairs) or any(
        not resource.active or not grant.active for resource, grant in rows
    ):
        raise ValueError("Exact managed plan resource/grant pairs are unavailable")
    deadlines = {grant.expires_at for _, grant in rows if grant.expires_at is not None}
    source_resources = {resource.resource_id for resource, _ in rows if resource.kind == "source"}
    heads = await _plan_source_heads(session, work, source_resources)
    deadlines.update(head.fresh_until for _, head in heads if head.fresh_until is not None)
    return tuple(sorted(deadlines))


async def _plan_source_heads(
    session: AsyncSession,
    work: ExecutionWork,
    source_resources: set[UUID],
) -> tuple[tuple[BrainSource, BrainSourceHead], ...]:
    heads = tuple(
        (
            await session.execute(
                select(BrainSource, BrainSourceHead)
                .join(
                    BrainSourceHead,
                    (BrainSourceHead.company_id == BrainSource.company_id)
                    & (BrainSourceHead.source_id == BrainSource.source_id),
                )
                .where(
                    BrainSource.company_id == work.company_id,
                    BrainSource.resource_id.in_(source_resources),
                )
                .limit(65)
            )
        ).all()
    )
    if len(heads) > 64 or {source.resource_id for source, _ in heads} != source_resources:
        raise ValueError("Exact managed plan source heads are unavailable or unbounded")
    if any(head.availability != "available" for _, head in heads):
        raise ValueError("Exact managed plan source is unavailable")
    return tuple((source, head) for source, head in heads)
