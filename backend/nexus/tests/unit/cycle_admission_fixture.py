"""Declared eleven-slot pure scenario; no database, SDK, provider or current authority."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from nexus.company.contracts.work import WorkItem, WorkPlan
from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import REPORT_CHECK_CRITERIA
from nexus.company.management.cycle_admission_contracts import (
    StockFlowCycleAdmission,
    StockFlowCycleSlot,
)
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.governance import CharterRevisionRef
from nexus.company.management.native_execution_profiles import NATIVE_CRITERIA
from nexus.company.management.plans import (
    ChildAllocation,
    PlanPayload,
    ProcedureRoot,
    RunBinding,
    VerificationIntent,
)
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.standing_contracts import ToolPermission


@dataclass(frozen=True)
class Cycle:
    admission: StockFlowCycleAdmission
    registry: ModelRegistry
    strategy: PlanPayload
    full: PlanPayload


def cycle() -> Cycle:
    """Closed declared fixture; no membership/model-health/current-state assertion."""
    # This >50-line fixture keeps all eleven distinct role/edge/quota pins in one scenario.
    company, workspace = UUID(int=1), UUID(int=2)
    registry = ModelRegistry(company_id=company, revision="cycle-models-v1", pricebook_version="p1")
    mandate = RevisionRef(
        company_id=company, revision_id=UUID(int=5), version="v1", sha256="a" * 64
    )
    goal = GoalRevisionRef(
        **mandate.model_dump(exclude={"revision_id"}), revision_id=UUID(int=6), goal_id=UUID(int=7)
    )
    specs = (
        (
            "strategy",
            "company.cycle.artifact",
            "reasoning",
            ".08",
            1,
            "company.cycle-artifact.write.v1",
        ),
        (
            "strategy_check",
            "company.cycle.artifact",
            "verification",
            ".06",
            0,
            "company.cycle-artifact.check.v1",
        ),
        (
            "engineering",
            "engineering.change",
            "engineering.native.v1",
            ".20",
            0,
            "company.builder.run.v1",
        ),
        (
            "engineering_check",
            "engineering.verify",
            "verification.native.v1",
            ".20",
            0,
            "company.builder.run.v1",
        ),
        (
            "presentation",
            "company.cycle.artifact",
            "routine",
            ".08",
            1,
            "company.cycle-artifact.write.v1",
        ),
        (
            "presentation_check",
            "company.cycle.artifact",
            "verification",
            ".04",
            0,
            "company.cycle-artifact.check.v1",
        ),
        (
            "support",
            "company.cycle.artifact",
            "routine",
            ".08",
            1,
            "company.cycle-artifact.write.v1",
        ),
        (
            "support_check",
            "company.cycle.artifact",
            "verification",
            ".04",
            0,
            "company.cycle-artifact.check.v1",
        ),
        ("report", "internal.report", "routine", ".10", 0, "company.report.write.v1"),
        ("report_check", "internal.report", "verification", ".04", 0, "company.report.check.v1"),
        (
            "sender",
            "internal.owner-notification",
            "notification.native.v1",
            ".04",
            0,
            "company.owner-notification.send.v1",
        ),
    )
    slots = []
    for index, (role, workflow, profile, usd, models, tool) in enumerate(specs):
        bound = RunBinding(
            company_id=company,
            workspace_id=workspace,
            actor_id=UUID(int=100 + index),
            task_id=UUID(int=200 + index),
            trace_id=UUID(int=300 + index),
            run_id=UUID(int=400 + index),
            workflow_name=workflow,
            workflow_version="v1",
            model_profile=profile,
            model_registry_version=registry.revision,
        )
        charter = CharterRevisionRef(
            company_id=company,
            revision_id=UUID(int=500 + index),
            version="v1",
            sha256="b" * 64,
            department_id=UUID(int=600 + index),
        )
        dependencies = {
            2: (UUID(int=200),),
            4: (UUID(int=202),),
            6: (UUID(int=202),),
            8: (UUID(int=200), UUID(int=202), UUID(int=204), UUID(int=206)),
        }.get(index, ())
        criteria = (
            NATIVE_CRITERIA
            if index in (2, 3)
            else REPORT_CHECK_CRITERIA
            if index in (8, 9)
            else (f"cycle.{role}.v1",)
        )
        item = WorkItem(
            company_id=company,
            task_id=bound.task_id,
            trace_id=bound.trace_id,
            goal_id=goal.goal_id,
            department=role,
            title=f"Bounded {role}",
            acceptance=criteria,
            depends_on=dependencies,
            budget_usd=Decimal(usd),
        )
        child = ChildAllocation(
            company_id=company,
            binding=bound,
            charter=charter,
            allocation_usd=Decimal(usd),
            quota=AttemptQuota(
                model_requests=models, tool_attempts=1, rework_rounds=0, plan_revisions=0
            ),
        )
        edge = None
        if index in (1, 3, 5, 7, 9):
            recipe = {
                1: "stockflow-strategy-brief-v1",
                3: "native-engineering-change-v1",
                5: "stockflow-presentation-v1",
                7: "stockflow-support-v1",
                9: "internal-report-mechanical-v1",
            }[index]
            edge = VerificationIntent(
                company_id=company,
                author_task_id=UUID(int=199 + index),
                verifier_task_id=bound.task_id,
                check_recipe=recipe,
            )
        slots.append(
            StockFlowCycleSlot.model_validate(
                {
                    "role": role,
                    "child": child,
                    "work": item,
                    "tool": ToolPermission(tool=tool, tool_version="v1", resource="cycle.output"),
                    "verification": edge,
                }
            )
        )
    root = ProcedureRoot(
        company_id=company,
        procedure_id=UUID(int=8),
        goal_id=goal.goal_id,
        binding=slots[0].child.binding.model_copy(
            update={"task_id": UUID(int=9), "trace_id": UUID(int=10), "run_id": UUID(int=11)}
        ),
        allocation_usd=Decimal("1"),
        quota=AttemptQuota(model_requests=3, tool_attempts=11, rework_rounds=0, plan_revisions=1),
    )
    admission = StockFlowCycleAdmission(
        company_id=company,
        goal=goal,
        mandate=mandate,
        plan_id=UUID(int=12),
        registry_revision=registry.revision,
        registry_sha256=canonical_sha256(registry),
        procedure=root,
        slots=tuple(slots),
    )
    return Cycle(admission, registry, declared(admission, 1), declared(admission, 2))


def declared(admission: StockFlowCycleAdmission, revision: int) -> PlanPayload:
    slots = admission.slots[:2] if revision == 1 else admission.slots
    return PlanPayload(
        company_id=admission.company_id,
        goal=admission.goal,
        mandate=admission.mandate,
        procedure=admission.procedure,
        charters=tuple(row.child.charter for row in slots),
        children=tuple(row.child for row in slots),
        verification=tuple(row.verification for row in slots if row.verification is not None),
        plan=WorkPlan(
            company_id=admission.company_id,
            plan_id=admission.plan_id,
            goal_id=admission.goal.goal_id,
            revision=revision,
            items=tuple(row.work for row in slots),
        ),
    )
