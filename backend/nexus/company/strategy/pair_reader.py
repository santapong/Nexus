"""Private actual current strategy pair resolution; no report recipe or supplied pass selector."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_support import stored_plan
from nexus.company.management.acceptance_targets import current_governance, current_work
from nexus.company.management.cancellation_support import require_not_cancelled
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanRevision,
    ManagementProcedure,
    ManagementVerificationBinding,
)
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import ChildAllocation, PlanPayload, RunBinding
from nexus.company.management.report_input_contracts import native_author
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.company.strategy.contracts import (
    STRATEGY_CHECK_CRITERIA,
    STRATEGY_CHECK_RECIPE,
    StrategyCheckSnapshot,
    StrategyScope,
)
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True)
class StrategyNativePair:
    """Native facts only; current source, credential and effect gates remain separate."""

    plan: PlanPayload
    author: ExecutionWork
    verifier: ExecutionWork
    author_child: ChildAllocation
    verifier_child: ChildAllocation


def require_current_strategy_author(author: ExecutionWork) -> None:
    """Use the existing current-target state policy; this is not historical receipt audit."""
    require_acceptance(author.state not in {"outcome_unknown", "blocked"})


def require_pair_layout(payload: PlanPayload, scope: StrategyScope) -> None:
    """A retained original pair must remain exact even when more goal children are added."""
    selected = {row.binding.task_id: row for row in payload.children}
    works = {row.task_id: row for row in payload.plan.items}
    relevant = tuple(
        row
        for row in payload.verification
        if (
            row.author_task_id in {scope.author.task_id, scope.verifier.task_id}
            or row.verifier_task_id in {scope.author.task_id, scope.verifier.task_id}
        )
    )
    require_acceptance(
        payload.company_id == scope.company_id
        and payload.goal == scope.goal
        and scope.author.task_id in selected
        and scope.verifier.task_id in selected
        and selected[scope.author.task_id].binding == scope.author
        and selected[scope.verifier.task_id].binding == scope.verifier
        and tuple((row.author_task_id, row.verifier_task_id, row.check_recipe) for row in relevant)
        == ((scope.author.task_id, scope.verifier.task_id, STRATEGY_CHECK_RECIPE),)
        and works[scope.author.task_id].acceptance == STRATEGY_CHECK_CRITERIA
        and works[scope.verifier.task_id].acceptance == STRATEGY_CHECK_CRITERIA
    )


async def _plan(
    session: AsyncSession,
    company: UUID,
    reference: PlanRevisionRef,
) -> tuple[ManagementPlanRevision, PlanPayload]:
    row = await session.get(ManagementPlanRevision, (company, reference.plan_revision_id))
    require_acceptance(row is not None)
    assert row is not None
    require_acceptance(
        (row.plan_id, row.plan_revision_id, row.revision, row.sha256)
        == (reference.plan_id, reference.plan_revision_id, reference.revision, reference.sha256)
    )
    return row, stored_plan(row, company)


async def _edges(
    session: AsyncSession, company: UUID, revision: UUID, scope: StrategyScope
) -> None:
    tasks = (scope.author.task_id, scope.verifier.task_id)
    rows = tuple(
        (
            await session.scalars(
                select(ManagementVerificationBinding)
                .where(
                    ManagementVerificationBinding.company_id == company,
                    ManagementVerificationBinding.plan_revision_id == revision,
                    or_(
                        ManagementVerificationBinding.author_task_id.in_(tasks),
                        ManagementVerificationBinding.verifier_task_id.in_(tasks),
                    ),
                )
                .limit(3)
            )
        ).all()
    )
    require_acceptance(len(rows) == 1)
    row = rows[0]
    require_acceptance(
        (row.author_task_id, row.verifier_task_id, row.check_recipe)
        == (scope.author.task_id, scope.verifier.task_id, STRATEGY_CHECK_RECIPE)
    )


async def _permanent_root(
    session: AsyncSession,
    company: UUID,
    original: PlanPayload,
    current: PlanPayload,
    author: ExecutionWork,
    verifier: ExecutionWork,
) -> None:
    require_acceptance(original.procedure == current.procedure)
    expected = original.procedure
    procedure = await session.get(ManagementProcedure, (company, expected.procedure_id))
    root = await session.get(ExecutionWork, (company, expected.binding.task_id))
    require_acceptance(procedure is not None and root is not None)
    assert procedure is not None and root is not None
    binding, registration = native_author(root)
    require_acceptance(
        binding == expected.binding
        and root.parent_task_id is None
        and author.parent_task_id == verifier.parent_task_id == root.task_id
        and (
            procedure.goal_id,
            procedure.parent_task_id,
            procedure.parent_run_id,
            procedure.allocation_usd,
        )
        == (expected.goal_id, root.task_id, root.run_id, expected.allocation_usd)
        and RunBinding.model_validate_json(procedure.binding_json) == binding
        and AttemptQuota.model_validate_json(procedure.quota_json) == expected.quota
        and registration.quota == expected.quota
        and registration.work.budget_usd == expected.allocation_usd
        and registration.work.goal_id == expected.goal_id
        and await ManagementPlanStore.managed_kind(session, company, root.task_id) == "procedure"
    )


async def resolve_strategy_pair_locked(
    session: AsyncSession,
    control: CompanyControl,
    original: StrategyCheckSnapshot,
) -> StrategyNativePair:
    """Resolve actual approved current/original plan, exact pair and permanent registrations."""
    # The cohesive >50-line pair gate preserves exact old provenance across the current plan head.
    await require_strategy_application_role(session)
    scope, company = original.scope, original.company_id
    require_acceptance(
        session.in_transaction() and control.company_id == company and not control.paused
    )
    first = await ManagementPlanStore.current_binding(session, company, scope.author.task_id)
    second = await ManagementPlanStore.current_binding(session, company, scope.verifier.task_id)
    require_acceptance(first is not None and second is not None)
    assert first is not None and second is not None
    require_acceptance(first.plan == second.plan and first.procedure_id == second.procedure_id)
    _, current = await _plan(session, company, first.plan)
    old_row, old = await _plan(session, company, scope.producing_plan)
    require_pair_layout(old, scope)
    require_pair_layout(current, scope)
    require_acceptance(old.mandate == current.mandate and first.plan.revision in {1, 2})
    decisions = tuple(
        (
            await session.scalars(
                select(ManagementOwnerDecision)
                .where(
                    ManagementOwnerDecision.company_id == company,
                    ManagementOwnerDecision.plan_revision_id == old_row.plan_revision_id,
                    ManagementOwnerDecision.kind == "approve",
                )
                .limit(2)
            )
        ).all()
    )
    require_acceptance(len(decisions) == 1)
    require_acceptance(
        decisions[0].owner_id == control.owner_id and decisions[0].payload_sha256 == old_row.sha256
    )
    await _edges(session, company, old_row.plan_revision_id, scope)
    await _edges(session, company, first.plan.plan_revision_id, scope)
    await current_governance(session, control, current)
    author, author_child, author_charter = await current_work(
        session, control, current, first.plan.plan_revision_id, scope.author.task_id
    )
    require_current_strategy_author(author)
    verifier, verifier_child, _ = await current_work(
        session, control, current, first.plan.plan_revision_id, scope.verifier.task_id
    )
    author_binding, registration = native_author(author)
    verifier_binding, _ = native_author(verifier)
    old_children = {row.binding.task_id: row for row in old.children}
    require_acceptance(
        (author_binding, verifier_binding) == (scope.author, scope.verifier)
        and author.actor_id != verifier.actor_id
        and author_charter.verifier_id == verifier.actor_id
        and registration == original.author_registration
        and registration_digest(registration) == scope.author_registration_sha256
        and author_child == old_children[author.task_id]
        and verifier_child == old_children[verifier.task_id]
        and first.work_sha256 == author.registration_hash
        and second.work_sha256 == verifier.registration_hash
    )
    await require_not_cancelled(session, company, author.task_id)
    await require_not_cancelled(session, company, verifier.task_id)
    await _permanent_root(session, company, old, current, author, verifier)
    return StrategyNativePair(current, author, verifier, author_child, verifier_child)
