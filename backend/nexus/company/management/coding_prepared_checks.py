"""Actual C registration/root/source checks before protected coding bytes.

Cohesion exception: current execution and historical financial metadata share the
same closed native conditions, while deliberately retaining different freshness
rules. Keeping both here prevents historical billing from borrowing C authority.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.native_fact_inputs import source_artifact_reference
from nexus.company.brain.retrieval_records import heads, revision_ref
from nexus.company.brain.source_models import BrainSource, BrainSourceRevision
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.contracts.work import WorkItem
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.acceptance_provenance import reference_sources
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_prepared_contracts import (
    CodingPreparedHeader,
    header_reference,
    prepared_reference,
)
from nexus.company.management.cycle_cost_contracts import HistoricalCostSources
from nexus.company.management.nexus_coding_admission import NexusCodingAdmission
from nexus.company.management.nexus_coding_catalog import (
    coding_work_matches_template,
    select_configured_nexus_plan,
)
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.plan_registration import registration
from nexus.company.management.planning_native_facts import require_time
from nexus.company.management.planning_prepared_checks import NativePrepared, native_prepared
from nexus.company.management.revision_store import plan_record
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now, registration_digest, snapshot
from nexus.harness.journal_models import CompanyControl
from nexus.harness.model_authorizer_contracts import ModelInputRecipe


@dataclass(frozen=True, slots=True)
class CodingNative:
    current: NativePrepared
    root_registration_sha256: str


async def root_registration(
    session: AsyncSession, admission: NexusCodingAdmission, *, historical: bool = False
) -> str:
    root, slot = admission.procedure, admission.slots[1]
    actual = await session.get(ExecutionWork, (admission.company_id, root.binding.task_id))
    child = await session.get(RegisteredWork, (admission.company_id, slot.work.task_id))
    directory = await session.get(RegisteredWork, (admission.company_id, root.binding.task_id))
    item = WorkItem(
        company_id=admission.company_id,
        task_id=root.binding.task_id,
        trace_id=root.binding.trace_id,
        goal_id=root.goal_id,
        department="management",
        title="Non-executing goal procedure allocation",
        acceptance=("management.non-executing-allocation.v1",),
        budget_usd=root.allocation_usd,
    )
    if (
        actual is None
        or snapshot(actual).registration != registration(root.binding, item, root.quota)
        or actual.registration_hash != registration_digest(snapshot(actual).registration)
        or child is None
        or directory is None
        or (not historical and (not child.active or not directory.active))
        or (child.parent_task_id, child.root_task_id, child.allocation_usd)
        != (root.binding.task_id, root.binding.task_id, slot.child.allocation_usd)
        or (directory.parent_task_id, directory.root_task_id, directory.allocation_usd)
        != (None, root.binding.task_id, root.allocation_usd)
        or (child.actor_id, child.workspace_id, child.trace_id)
        != (
            slot.child.binding.actor_id,
            slot.child.binding.workspace_id,
            slot.child.binding.trace_id,
        )
    ):
        raise ManagementDeniedError("Coding permanent root/child/native registration differs")
    return actual.registration_hash


async def current_native(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    catalog: PlanAdmissionCatalog,
    task_id: UUID,
    action_id: UUID,
    recipe: ModelInputRecipe,
    *,
    lease: ExecutionLease | None,
    mode: Literal["owner", "actor", "worker"],
) -> CodingNative:
    admission = catalog.nexus_coding_admission
    if type(admission) is not NexusCodingAdmission or task_id != admission.slots[1].work.task_id:
        raise ManagementDeniedError("Coding requires its exact configured C slot")
    native = await native_prepared(
        session, control, scope, identity, task_id, action_id, recipe, lease=lease, reader=mode
    )
    row = await session.get(
        ManagementPlanRevision, (scope.company_id, native.current.plan.plan_revision_id)
    )
    if row is None:
        raise ManagementDeniedError("Coding approved execution plan is unavailable")
    plan = plan_record(row)
    slot = admission.slots[1]
    if (
        plan.sha256 != canonical_sha256(plan.payload)
        or plan.sha256 != native.current.plan.sha256
        or select_configured_nexus_plan(catalog, plan.payload) != "execution"
        or plan.payload.coding_admission_sha256 != canonical_sha256(admission)
        or native.current.child != slot.child
        or not coding_work_matches_template(native.current.work, slot.work)
        or native.current.work not in plan.payload.plan.items
        or native.current.procedure_id != admission.procedure.procedure_id
        or native.goal != admission.goal
    ):
        raise ManagementDeniedError("Coding current Goal/plan/full profile/C allocation differs")
    return CodingNative(native, await root_registration(session, admission))


def conditions(header: CodingPreparedHeader) -> tuple[ResourceRevision, ...]:
    reference, _ = header_reference(header)
    return (
        tuple(
            ResourceRevision(
                resource=f"brain.resource:{row.resource_id}", revision=f"acl:{row.generation}"
            )
            for row in header.contributors
        )
        + tuple(
            ResourceRevision(
                resource=f"brain.source:{row.source_id}",
                revision=f"head:{row.generation}:{row.current.source_revision_id}",
            )
            for row in header.source_heads
        )
        + (reference.condition,)
    )


def require_action_header(action: ActionProposal, header: CodingPreparedHeader) -> None:
    reference, _ = header_reference(header)
    if (
        prepared_reference(action) != reference
        or action.parameters != header.parameters.model_dump(mode="json")
        or action.preconditions != conditions(header)
        or action.resource != f"model:{header.parameters.registry_id}"
        or (
            action.company_id,
            action.action_id,
            action.task_id,
            action.trace_id,
            action.actor_id,
            action.tool,
            action.tool_version,
        )
        != (
            header.company_id,
            header.action_id,
            header.task_id,
            header.trace_id,
            header.actor_id,
            "model.request.v1",
            "v1",
        )
    ):
        raise ManagementDeniedError(
            "Coding header differs from all exact native model parameters/conditions"
        )


def require_native_header(
    native: CodingNative,
    header: CodingPreparedHeader,
    admission: NexusCodingAdmission,
    recipe: ModelInputRecipe,
) -> None:
    current, root = native.current, admission.procedure
    binding = current.current.child.binding
    if (
        (
            header.owner_id,
            header.registration_sha256,
            header.run_id,
            header.goal,
            header.plan,
            header.actor_id,
            header.workspace_id,
            header.task_id,
            header.trace_id,
        )
        != (
            current.owner_id,
            current.registration_sha256,
            current.run_id,
            current.goal,
            current.current.plan,
            binding.actor_id,
            binding.workspace_id,
            binding.task_id,
            binding.trace_id,
        )
        or (
            header.root_task_id,
            header.root_run_id,
            header.root_registration_sha256,
            header.procedure_id,
        )
        != (
            root.binding.task_id,
            root.binding.run_id,
            native.root_registration_sha256,
            root.procedure_id,
        )
        or header.admission_sha256 != canonical_sha256(admission)
        or header.input_recipe_sha256 != canonical_sha256(recipe)
        or (
            header.parameters.registry_revision,
            header.parameters.input_recipe_id,
            header.parameters.input_recipe_revision,
        )
        != (binding.model_registry_version, recipe.recipe_id, recipe.revision)
    ):
        raise ManagementDeniedError("Coding immutable header/root/Goal/head/recipe differs")
    if current.proposal is not None:
        require_action_header(current.proposal, header)


def shorten(end_us: int, before: int, now: datetime, windows: tuple[datetime, ...]) -> int:
    if any(value <= now for value in windows):
        raise ManagementDeniedError("Coding original source/identity/lease window expired")
    result = min(
        (end_us, *(before + (value - now) // timedelta(microseconds=1) for value in windows))
    )
    require_time(result)
    return result


async def require_code_metadata(
    session: AsyncSession,
    scope: BrainReadScope,
    header: CodingPreparedHeader,
) -> None:
    """The nominated Git metadata must describe actual registered source/artifact rows."""
    for code in header.code_sources:
        row = await session.get(
            BrainSourceRevision, (scope.company_id, code.source.source_revision_id)
        )
        source = await session.get(BrainSource, (scope.company_id, code.source.source_id))
        if (
            row is None
            or source is None
            or revision_ref(row) != code.source
            or (source.source_symbol, source.external_key)
            != (code.git.source_symbol, code.git.external_key)
            or (row.source_event_precision, row.source_event_value, row.source_event_basis)
            != (
                code.git.source_event.precision,
                code.git.source_event.value,
                code.git.source_event.basis,
            )
            or await source_artifact_reference(session, scope, row.artifact_revision_id)
            != code.artifact
        ):
            raise ManagementDeniedError(
                "Coding Git selection differs from actual registered source metadata"
            )


async def source_read(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    header: CodingPreparedHeader,
    sources: OwnerViewSources,
) -> tuple[datetime, ...]:
    original = tuple(row.expires_at for row in header.contributors if row.expires_at is not None)
    original += tuple(row.fresh_until for row in header.source_heads if row.fresh_until is not None)
    now = await db_now(session)
    if any(value <= now for value in original):
        raise ManagementDeniedError("Original coding source window expired")
    ids = tuple(row.resource_id for row in header.contributors)
    grants = await require_resources(session, scope, ids, await db_now(session))
    if (
        tuple((row.resource_id, row.generation) for row in grants)
        != tuple((row.resource_id, row.generation) for row in header.contributors)
        or await heads(session, scope, tuple(row.current for row in header.source_heads))
        != header.source_heads
    ):
        raise ManagementDeniedError("Coding current source heads/ACL changed")
    artifacts = {}
    revisions = {}
    for head in header.source_heads:
        row = await session.get(
            BrainSourceRevision, (scope.company_id, head.current.source_revision_id)
        )
        if row is None or revision_ref(row) != head.current:
            raise ManagementDeniedError("Coding exact native source revision is unavailable")
        revisions[row.source_revision_id] = row
        ref = await source_artifact_reference(session, scope, row.artifact_revision_id)
        artifacts[ref.artifact_revision_id] = ref
    for code in header.code_sources:
        row = revisions.get(code.source.source_revision_id)
        if (
            row is None
            or revision_ref(row) != code.source
            or artifacts.get(code.artifact.artifact_revision_id) != code.artifact
        ):
            raise ManagementDeniedError(
                "Coding Git/artifact provenance differs from native sources"
            )
    await require_code_metadata(session, scope, header)
    source_ids, resources = await reference_sources(session, scope, tuple(artifacts.values()))
    if set(resources) != set(ids) or set(source_ids) != {
        row.source_id for row in header.source_heads
    }:
        raise ManagementDeniedError("Coding complete native contributors differ")
    for ref in artifacts.values():
        await sources.artifacts.revalidate_artifact_reference(
            session, control, scope, identity, ref, await db_now(session)
        )
    await sources.freshness.revalidate_references(
        session, scope, tuple(artifacts.values()), await db_now(session)
    )
    windows = original + tuple(row.expires_at for row in grants if row.expires_at is not None)
    final = await db_now(session)
    if any(value <= final for value in windows):
        raise ManagementDeniedError("Coding source READ expired")
    return windows


async def action_sources(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    action: ActionProposal,
    sources: OwnerViewSources,
    *,
    historical: bool,
) -> tuple[str, tuple[datetime, ...]]:
    """Native conditions authorize metadata read before the small header itself is opened."""
    if type(sources.freshness) is not RegisteredSourceFreshness:
        raise ManagementDeniedError("Coding requires its concrete source freshness registry")
    marker = prepared_reference(action).condition
    resources, refs = [], []
    source_conditions = []
    for condition in action.preconditions:
        if condition == marker:
            continue
        if condition.resource.startswith("brain.resource:"):
            key = UUID(condition.resource.removeprefix("brain.resource:"))
            generation = int(condition.revision.removeprefix("acl:"))
            if generation < 1 or condition != ResourceRevision(
                resource=f"brain.resource:{key}", revision=f"acl:{generation}"
            ):
                raise ValueError("Coding native ACL condition is not canonical")
            resources.append((key, generation))
        elif condition.resource.startswith("brain.source:"):
            key = UUID(condition.resource.removeprefix("brain.source:"))
            parts = condition.revision.split(":")
            if len(parts) != 3 or parts[0] != "head" or not parts[1].isdecimal():
                raise ValueError("Coding native source condition is not canonical")
            generation, revision = int(parts[1]), UUID(parts[2])
            if generation < 1 or condition != ResourceRevision(
                resource=f"brain.source:{key}", revision=f"head:{generation}:{revision}"
            ):
                raise ValueError("Coding native source condition differs")
            row = await session.get(BrainSourceRevision, (scope.company_id, revision))
            if row is None or row.source_id != key:
                raise ValueError("Coding historical source revision is unavailable")
            refs.append(revision_ref(row))
            source_conditions.append((key, generation, revision))
        else:
            raise ValueError("Unrecognized coding source/preparation condition")
    if (
        not 0 < len(resources) <= 32
        or not 0 < len(refs) <= 32
        or len(set(resources)) != len(resources)
        or len({row.source_id for row in refs}) != len(refs)
    ):
        raise ValueError("Coding native source closure is incomplete/duplicated")
    grants = await require_resources(
        session, scope, tuple(sorted(key for key, _ in resources)), await db_now(session)
    )
    current_heads = await heads(session, scope, tuple(refs))
    if not historical and (
        set(resources) != {(row.resource_id, row.generation) for row in grants}
        or source_conditions
        != [
            (row.source_id, row.generation, row.current.source_revision_id) for row in current_heads
        ]
    ):
        raise ManagementDeniedError("Coding current native source/ACL conditions changed")
    artifacts = []
    windows: list[datetime] = []
    for ref in refs:
        row = await session.get(BrainSourceRevision, (scope.company_id, ref.source_revision_id))
        if row is None:
            raise ValueError("Coding historical source disappeared")
        artifact = await source_artifact_reference(session, scope, row.artifact_revision_id)
        artifacts.append(artifact)
        if historical:
            windows.extend(
                await sources.artifacts.revalidate_historical_artifact_reference(
                    session, control, scope, identity, artifact, await db_now(session)
                )
            )
        else:
            await sources.artifacts.revalidate_artifact_reference(
                session, control, scope, identity, artifact, await db_now(session)
            )
    source_ids, actual_resources = await reference_sources(session, scope, tuple(artifacts))
    if set(source_ids) != {row.source_id for row in refs} or set(actual_resources) != {
        key for key, _ in resources
    }:
        raise ManagementDeniedError("Coding native condition closure omits source contributors")
    if historical:
        windows.extend(
            await sources.freshness.revalidate_historical_references(
                session, scope, tuple(artifacts), await db_now(session)
            )
        )
    else:
        await sources.freshness.revalidate_references(
            session, scope, tuple(artifacts), await db_now(session)
        )
        windows.extend(row.fresh_until for row in current_heads if row.fresh_until is not None)
    policies = await sources.freshness.capture_plan_heads_locked(
        session, scope, tuple(sorted(row.source_id for row in refs)), await db_now(session)
    )
    windows.extend(row.expires_at for row in grants if row.expires_at is not None)
    signature = canonical_sha256(
        HistoricalCostSources(
            grants=grants, heads=current_heads, policies=tuple(row.policy for row in policies)
        )
    )
    return signature, tuple(windows)
