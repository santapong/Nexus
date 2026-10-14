"""Actual public approved UAT allocations; no provider, queue or effect starts here."""

from decimal import Decimal
from uuid import UUID, uuid5

from nexus.company.contracts.work import WorkItem, WorkPlan
from nexus.company.management.base import RevisionRef
from nexus.company.management.check_contracts import REPORT_CHECK_CRITERIA, REPORT_CHECK_RECIPE
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.plans import (
    ChildAllocation,
    PlanPayload,
    ProcedureRoot,
    RunBinding,
    VerificationIntent,
)
from nexus.company.pilot_composition import PilotServices
from nexus.company.pilot_config import PilotConfig
from nexus.execution.runtime_contracts import AttemptQuota


def bound(config: PilotConfig, name: str, actor: UUID, profile: str = "routine") -> RunBinding:
    return RunBinding(
        company_id=config.company_id,
        workspace_id=config.workspace_id,
        actor_id=actor,
        task_id=uuid5(config.company_id, "uat-task:" + name),
        trace_id=uuid5(config.company_id, "uat-trace:" + name),
        run_id=uuid5(config.company_id, "uat-run:" + name),
        workflow_name="internal.report",
        workflow_version="v1",
        model_profile=profile,
        model_registry_version="uat-only-offline-v1",
    )


def work_items(
    config: PilotConfig, children: tuple[ChildAllocation, ...], verifier: RunBinding
) -> tuple[WorkItem, ...]:
    return tuple(
        WorkItem(
            company_id=config.company_id,
            task_id=row.binding.task_id,
            trace_id=row.binding.trace_id,
            goal_id=config.goal_id,
            department="UAT report verifier" if row.binding == verifier else "UAT report author",
            title="Synthetic UAT " + name,
            acceptance=REPORT_CHECK_CRITERIA,
            budget_usd=row.allocation_usd,
        )
        for row, name in zip(children, ("author", "verifier", "idle observation"), strict=True)
    )


def child_allocations(
    config: PilotConfig,
    charters: tuple[CharterRevisionRef, ...],
    values: tuple[RunBinding, ...],
    verifier: RunBinding,
) -> tuple[ChildAllocation, ...]:
    return tuple(
        ChildAllocation(
            company_id=config.company_id,
            binding=value,
            charter=charters[1] if value == verifier else charters[0],
            allocation_usd=Decimal("0.2"),
            quota=AttemptQuota(
                model_requests=0, tool_attempts=1, rework_rounds=0, plan_revisions=0
            ),
        )
        for value in values
    )


def native_payload(
    config: PilotConfig,
    mandate: RevisionRef,
    charters: tuple[CharterRevisionRef, ...],
    goal: GoalRevisionRef,
) -> PlanPayload:
    author, verifier, idle = (
        bound(config, "author", config.author_id),
        bound(config, "verifier", config.verifier_id, "verification"),
        bound(config, "idle", config.author_id),
    )
    children = child_allocations(config, charters, (author, verifier, idle), verifier)
    return PlanPayload(
        company_id=config.company_id,
        mandate=mandate,
        charters=charters,
        goal=goal,
        children=children,
        plan=WorkPlan(
            company_id=config.company_id,
            plan_id=uuid5(config.company_id, "uat-plan"),
            goal_id=config.goal_id,
            revision=1,
            items=work_items(config, children, verifier),
        ),
        procedure=ProcedureRoot(
            company_id=config.company_id,
            procedure_id=uuid5(config.company_id, "uat-procedure"),
            goal_id=config.goal_id,
            binding=bound(config, "procedure", config.owner_id),
            allocation_usd=Decimal("0.8"),
            quota=AttemptQuota(),
        ),
        verification=(
            VerificationIntent(
                company_id=config.company_id,
                author_task_id=author.task_id,
                verifier_task_id=verifier.task_id,
                check_recipe=REPORT_CHECK_RECIPE,
            ),
        ),
    )


async def populate_plan(
    services: PilotServices,
    config: PilotConfig,
    mandate: RevisionRef,
    charters: tuple[CharterRevisionRef, ...],
    goal: GoalRevisionRef,
) -> tuple[PlanRevision, PlanPayload]:
    payload = native_payload(config, mandate, charters, goal)
    proposed = await services.management.plans.propose(
        config.control(), config.identity(), payload, expected_current_revision_id=None
    )
    approved = await services.management.plans.approve_and_register(
        config.control(),
        config.identity(),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=proposed.plan_revision_id,
    )
    return approved, payload
