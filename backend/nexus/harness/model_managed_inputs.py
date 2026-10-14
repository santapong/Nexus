"""Actual plan resources and accepted dependency/verifier selectors, never permits."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_support import actual_receipt, receipt_artifacts
from nexus.company.management.control_support import charter_record
from nexus.company.management.governance_models import ManagementCharterRevision
from nexus.company.management.plan_models import (
    ManagementPlanDependency,
    ManagementPlanRevision,
    ManagementVerificationBinding,
)
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import PlanPayload
from nexus.company.management.revision_store import plan_record
from nexus.execution.management_checks import current_accepted_work
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True, slots=True)
class ManagedModelInputs:
    payload: PlanPayload
    own_resource_ids: tuple[UUID, ...]
    plan_resource_ids: tuple[UUID, ...]
    grant_pairs: tuple[tuple[UUID, UUID], ...]
    artifacts: tuple[ArtifactRevisionRef, ...]


async def load_managed_model_inputs(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    identity: VerifiedIdentity,
    management: ManagementExecutionServices,
) -> ManagedModelInputs | None:
    kind = await ManagementPlanStore.managed_kind(session, work.company_id, work.task_id)
    if kind == "unmanaged":
        return None
    binding = await ManagementPlanStore.current_binding(session, work.company_id, work.task_id)
    if kind != "managed" or binding is None:
        raise ValueError("Current managed model plan binding is unavailable")
    native = await session.get(
        ManagementPlanRevision, (work.company_id, binding.plan.plan_revision_id)
    )
    if native is None:
        raise ValueError("Current managed model plan record is unavailable")
    payload = plan_record(native).payload
    own, pairs = await _plan_resources(session, work, payload, management)
    refs = await _dependency_artifacts(
        session,
        control,
        work,
        identity,
        management,
        binding.plan.plan_revision_id,
        binding.work.depends_on,
    )
    refs += await _verifier_artifacts(session, work, binding.plan.plan_revision_id)
    unique: dict[UUID, ArtifactRevisionRef] = {}
    for ref in refs:
        if ref.artifact_revision_id in unique and unique[ref.artifact_revision_id] != ref:
            raise ValueError("Managed model artifact revision references conflict")
        unique[ref.artifact_revision_id] = ref
    artifacts = tuple(unique[key] for key in sorted(unique))
    if len(artifacts) > 33 or sum(ref.byte_length for ref in artifacts) > 8_650_752:
        raise ValueError("Managed model artifact closure exceeds its bound")
    return ManagedModelInputs(payload, own, tuple(sorted({r for r, _ in pairs})), pairs, artifacts)


async def _plan_resources(
    session: AsyncSession,
    work: ExecutionWork,
    payload: PlanPayload,
    management: ManagementExecutionServices,
) -> tuple[tuple[UUID, ...], tuple[tuple[UUID, UUID], ...]]:
    mapping = {row.symbol: row.resource for row in management.catalog.resources}
    own: set[UUID] = set()
    pairs: set[tuple[UUID, UUID]] = set()
    for child in payload.children:
        row = await session.get(
            ManagementCharterRevision, (work.company_id, child.charter.revision_id)
        )
        if row is None:
            raise ValueError("Actual model plan charter is unavailable")
        charter = (await charter_record(session, row)).charter
        if not set(charter.resource_scopes) <= mapping.keys():
            raise ValueError("Declared managed model resource is not configured")
        for symbol in charter.resource_scopes:
            resource = mapping[symbol]
            if resource.company_id != work.company_id:
                raise ValueError("Managed model resource belongs to another company")
            pairs.update(
                (resource.resource_id, principal)
                for principal in (
                    child.binding.actor_id,
                    charter.verifier_id,
                )
            )
            if child.binding.task_id == work.task_id:
                own.add(resource.resource_id)
    if len(pairs) > 6400 or len({r for r, _ in pairs}) > 32:
        raise ValueError("Managed model plan resource pairs exceed their bound")
    return tuple(sorted(own)), tuple(sorted(pairs))


async def _dependency_artifacts(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    identity: VerifiedIdentity,
    management: ManagementExecutionServices,
    revision_id: UUID,
    expected: tuple[UUID, ...],
) -> tuple[ArtifactRevisionRef, ...]:
    rows = tuple(
        (
            await session.scalars(
                select(ManagementPlanDependency).where(
                    ManagementPlanDependency.company_id == work.company_id,
                    ManagementPlanDependency.plan_revision_id == revision_id,
                    ManagementPlanDependency.task_id == work.task_id,
                )
            )
        ).all()
    )
    if {row.dependency_task_id for row in rows} != set(expected):
        raise ValueError("Managed model dependencies differ from native plan")
    refs: list[ArtifactRevisionRef] = []
    for row in rows:
        dependency = await session.get(ExecutionWork, (work.company_id, row.dependency_task_id))
        if dependency is None:
            raise ValueError("Managed model dependency is unavailable")
        accepted = await current_accepted_work(
            session, control, work, dependency, identity, management.artifacts, management.freshness
        )
        if accepted is None:
            raise ValueError("Managed model dependency has no current independent acceptance")
        refs.extend(
            (*accepted.target.artifacts, *(proof.result_artifact for proof in accepted.proofs))
        )
    return tuple(refs)


async def _verifier_artifacts(
    session: AsyncSession,
    work: ExecutionWork,
    revision_id: UUID,
) -> tuple[ArtifactRevisionRef, ...]:
    edge = await session.get(
        ManagementVerificationBinding,
        (
            work.company_id,
            revision_id,
            work.task_id,
        ),
    )
    if edge is None:
        return ()
    author = await session.get(ExecutionWork, (work.company_id, edge.author_task_id))
    if author is None:
        raise ValueError("Managed model verifier author is unavailable")
    effect = await session.scalar(
        select(EffectIntent)
        .where(
            EffectIntent.company_id == work.company_id,
            EffectIntent.task_id == author.task_id,
            EffectIntent.run_id == author.run_id,
            EffectIntent.state == "succeeded",
        )
        .order_by(EffectIntent.created_at.desc(), EffectIntent.action_id.desc())
        .limit(1)
    )
    if effect is None:
        raise ValueError("Managed model verifier awaits actual issued author output")
    return await receipt_artifacts(session, await actual_receipt(session, author, effect.action_id))
