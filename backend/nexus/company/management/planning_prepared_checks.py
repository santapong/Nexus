"""Read-only native/source validation for protected preparations; never an SDK permit."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.native_fact_inputs import source_artifact_reference
from nexus.company.brain.retrieval_records import heads
from nexus.company.brain.source_models import BrainSourceRevision
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_provenance import reference_sources
from nexus.company.management.control_support import db_clock
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.governance_models import ManagementGoalHead, ManagementGoalRevision
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.plan_models import ManagementPlanHead
from nexus.company.management.plan_registration import registration
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.planning_prepared_contracts import PlanningPreparedDescriptor
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import require_lease, snapshot
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.model_authorizer_contracts import ModelInputRecipe


@dataclass(frozen=True, slots=True)
class NativePrepared:
    owner_id: UUID
    registration_sha256: str
    run_id: UUID
    goal: GoalRevisionRef
    current: CurrentPlanBinding
    proposal: ActionProposal | None
    proposal_sha256: str | None


async def native_prepared(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    task_id: UUID,
    action_id: UUID,
    recipe: ModelInputRecipe,
    *,
    lease: ExecutionLease | None,
    reader: Literal["owner", "actor", "worker"] = "owner",
) -> NativePrepared:
    """Use the actual signed principal; a stored actor ID never creates an identity."""
    work = await session.get(ExecutionWork, (scope.company_id, task_id))
    current = await ManagementPlanStore.current_binding(session, scope.company_id, task_id)
    if work is None or current is None:
        raise ManagementDeniedError("Current registered planning work is unavailable")
    registered = snapshot(work)
    binding = current.child.binding
    if (
        current.work_sha256 != work.registration_hash
        or registered.registration != registration(binding, current.work, current.child.quota)
        or (
            binding.company_id,
            binding.task_id,
            binding.trace_id,
            binding.actor_id,
            binding.workspace_id,
            binding.run_id,
            binding.model_profile,
            binding.model_registry_version,
        )
        != (
            work.company_id,
            work.task_id,
            work.trace_id,
            work.actor_id,
            work.workspace_id,
            work.run_id,
            work.model_profile,
            work.model_registry_version,
        )
        or work.model_profile != recipe.profile
        or current.work.goal_id != registered.registration.work.goal_id
    ):
        raise ManagementDeniedError("Planning immutable registration differs from current plan")
    if reader == "owner":
        if identity.principal_id != control.owner_id:
            raise ManagementDeniedError("Only the actual current owner can prepare/review input")
    else:
        if (
            identity.principal_id,
            identity.workspace_id,
            scope.task_id,
            scope.task_trace_id,
            scope.actor_id,
        ) != (work.actor_id, work.workspace_id, work.task_id, work.trace_id, work.actor_id):
            raise ManagementDeniedError("Planning input needs its actual acquired actor")
        if reader == "worker":
            if lease is None:
                raise ManagementDeniedError("Planning execution read requires its actual lease")
            require_lease(work, lease, await db_clock(session), execute=True)
        elif lease is not None:
            raise ManagementDeniedError("Data-only actor read cannot substitute a lease mode")
    goal_head = await session.get(ManagementGoalHead, (scope.company_id, current.work.goal_id))
    goal = (
        await session.get(ManagementGoalRevision, (scope.company_id, goal_head.current_revision_id))
        if goal_head
        else None
    )
    if goal_head is None or not goal_head.active or goal is None:
        raise ManagementDeniedError("Current planning goal is unavailable")
    reference = GoalRevisionRef(
        company_id=scope.company_id,
        goal_id=goal.goal_id,
        revision_id=goal.revision_id,
        version=goal.version,
        sha256=goal.sha256,
    )
    owner_scope = CompanyControlScope(
        company_id=scope.company_id,
        principal_id=identity.principal_id,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
    )
    actual = await GoalStore._current(session, owner_scope, reference)
    if actual.definition.owner_id != control.owner_id:
        raise ManagementDeniedError("Planning goal differs from its actual owner")
    row = await session.get(JournalAction, action_id)
    proposal = ActionProposal.model_validate_json(row.proposal_json) if row else None
    if proposal is not None and (
        row is None
        or action_hash(proposal) != row.proposal_hash
        or (row.company_id, row.task_id, row.trace_id, row.id)
        != (work.company_id, work.task_id, work.trace_id, action_id)
        or (
            proposal.company_id,
            proposal.task_id,
            proposal.trace_id,
            proposal.actor_id,
            proposal.action_id,
            proposal.tool,
            proposal.tool_version,
        )
        != (
            work.company_id,
            work.task_id,
            work.trace_id,
            work.actor_id,
            action_id,
            "model.request.v1",
            "v1",
        )
        or (reader == "worker" and (row.state != "authorized" or row.consumed_at is None))
    ):
        raise ManagementDeniedError("Actual native planning action differs")
    return NativePrepared(
        control.owner_id,
        work.registration_hash,
        work.run_id,
        reference,
        current,
        proposal,
        row.proposal_hash if row else None,
    )


async def require_native_header(
    session: AsyncSession,
    native: NativePrepared,
    header: PlanningPreparedDescriptor,
    recipe: ModelInputRecipe,
) -> None:
    """Fresh head/CAS and complete registered identities stay separate from private bytes."""
    binding = native.current.child.binding
    if (
        header.owner_id,
        header.registration_sha256,
        header.run_id,
        header.goal,
        header.actor_id,
        header.workspace_id,
        header.task_id,
        header.trace_id,
    ) != (
        native.owner_id,
        native.registration_sha256,
        native.run_id,
        native.goal,
        binding.actor_id,
        binding.workspace_id,
        binding.task_id,
        binding.trace_id,
    ) or (
        header.parameters.registry_revision,
        header.parameters.input_recipe_id,
        header.parameters.input_recipe_revision,
    ) != (binding.model_registry_version, recipe.recipe_id, recipe.revision):
        raise ManagementDeniedError("Planning descriptor goal/head/CAS/recipe or actor changed")
    target = await session.get(ManagementPlanHead, (header.company_id, header.plan_id))
    if (target.current_revision_id if target else None) != header.expected_plan_revision_id or (
        target is not None and target.goal_id != header.goal.goal_id
    ):
        raise ManagementDeniedError("Planning target plan CAS or goal changed")


async def source_read(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    header: PlanningPreparedDescriptor,
    sources: OwnerViewSources,
) -> tuple[datetime, ...]:
    """Actual source closure and this principal's READ precede private-body materialization."""
    original = tuple(row.expires_at for row in header.contributors if row.expires_at is not None)
    original += tuple(row.fresh_until for row in header.source_heads if row.fresh_until is not None)
    now = await db_clock(session)
    if any(end <= now for end in original):
        raise ManagementDeniedError("Original planning source/access window expired")
    ids = tuple(row.resource_id for row in header.contributors)
    grants = await require_resources(session, scope, ids, await db_clock(session))
    if (
        tuple((row.resource_id, row.generation) for row in grants)
        != tuple((row.resource_id, row.generation) for row in header.contributors)
        or await heads(session, scope, tuple(row.current for row in header.source_heads))
        != header.source_heads
    ):
        raise ManagementDeniedError("Planning source heads or ACL generation changed")
    references = {}
    for head in header.source_heads:
        row = await session.get(
            BrainSourceRevision, (scope.company_id, head.current.source_revision_id)
        )
        if row is None or row.source_id != head.source_id or row.revision != head.current.revision:
            raise ManagementDeniedError("Planning native source revision is unavailable")
        ref = await source_artifact_reference(session, scope, row.artifact_revision_id)
        references[ref.artifact_revision_id] = ref
    if references:
        source_ids, resources = await reference_sources(session, scope, tuple(references.values()))
        if set(resources) != set(ids) or set(source_ids) != {
            row.source_id for row in header.source_heads
        }:
            raise ManagementDeniedError("Planning descriptor omits native input contributors")
        for ref in references.values():
            await sources.artifacts.revalidate_artifact_reference(
                session, control, scope, identity, ref, await db_clock(session)
            )
        await sources.freshness.revalidate_references(
            session, scope, tuple(references.values()), await db_clock(session)
        )
    elif ids:
        raise ManagementDeniedError("Planning contributors lack native source provenance")
    deadlines = original + tuple(row.expires_at for row in grants if row.expires_at is not None)
    final = await db_clock(session)
    if any(end <= final for end in deadlines):
        raise ManagementDeniedError("Current planning source READ expired")
    return deadlines
