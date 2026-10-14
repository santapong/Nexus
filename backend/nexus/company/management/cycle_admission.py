"""Pure exact mixed-cycle matching; actual shared admission remains disabled."""

from nexus.company.contracts.work import WorkPlan
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import REPORT_CHECK_CRITERIA, REPORT_CHECK_RECIPE
from nexus.company.management.cycle_admission_contracts import (
    StockFlowCycleAdmission,
    StockFlowCycleSelection,
    StockFlowCycleSlot,
    require_exact_cycle_quota,
)
from nexus.company.management.native_execution_profiles import NATIVE_CRITERIA
from nexus.company.management.plans import PlanPayload
from nexus.core.llm.company_registry import ModelRegistry
from nexus.execution.runtime_contracts import AttemptQuota

_ROLE_ABI = (
    ("company.cycle.artifact", "reasoning", "company.cycle-artifact.write.v1", 1),
    ("company.cycle.artifact", "verification", "company.cycle-artifact.check.v1", 0),
    ("engineering.change", "engineering.native.v1", "company.builder.run.v1", 0),
    ("engineering.verify", "verification.native.v1", "company.builder.run.v1", 0),
    ("company.cycle.artifact", "routine", "company.cycle-artifact.write.v1", 1),
    ("company.cycle.artifact", "verification", "company.cycle-artifact.check.v1", 0),
    ("company.cycle.artifact", "routine", "company.cycle-artifact.write.v1", 1),
    ("company.cycle.artifact", "verification", "company.cycle-artifact.check.v1", 0),
    ("internal.report", "routine", "company.report.write.v1", 0),
    ("internal.report", "verification", "company.report.check.v1", 0),
    (
        "internal.owner-notification",
        "notification.native.v1",
        "company.owner-notification.send.v1",
        0,
    ),
)
_CHECKS = {
    1: "stockflow-strategy-brief-v1",
    3: "native-engineering-change-v1",
    5: "stockflow-presentation-v1",
    7: "stockflow-support-v1",
    9: REPORT_CHECK_RECIPE,
}
_DEPENDENCIES = {2: (0,), 4: (2,), 6: (2,), 8: (0, 2, 4, 6)}


def validate_stockflow_cycle_configuration(
    admission: StockFlowCycleAdmission,
    registry: ModelRegistry,
) -> StockFlowCycleAdmission:
    """Validate every original configuration slot before any selection/derived catalog."""
    # Python reconstruction preserves raw bool/float quotas that JSON could normalize.
    require_exact_cycle_quota(admission.procedure.quota)
    for original in admission.slots:
        require_exact_cycle_quota(original.child.quota)
    checked = StockFlowCycleAdmission.model_validate(admission.model_dump(warnings=False))
    actual = ModelRegistry.model_validate(registry.model_dump(warnings=False))
    if (
        checked.company_id != actual.company_id
        or checked.registry_revision != actual.revision
        or checked.registry_sha256 != canonical_sha256(actual)
        or canonical_sha256(actual) != canonical_sha256(registry)
    ):
        raise ValueError("Cycle configuration binds another complete original registry")
    for index, slot in enumerate(checked.slots):
        _slot_abi(checked, slot, index)
    quota = checked.procedure.quota
    if quota != AttemptQuota(model_requests=3, tool_attempts=11, rework_rounds=0, plan_revisions=1):
        raise ValueError("Cycle root lifetime quota differs from its finite partition")
    if sum(row.child.allocation_usd for row in checked.slots) > checked.procedure.allocation_usd:
        raise ValueError("Cycle children exceed their permanent USD root")
    root = checked.procedure.binding
    if (
        root.model_profile not in {"reasoning", "routine"}
        or root.model_registry_version != actual.revision
        or root.workflow_version != "v1"
    ):
        raise ValueError("Cycle nonexecuting root registry/profile differs")
    _validate_full_plan(checked)
    return checked


def _validate_full_plan(admission: StockFlowCycleAdmission) -> None:
    """Apply every existing full-plan invariant before selecting the smaller strategy stage."""
    slots = admission.slots
    PlanPayload(
        company_id=admission.company_id,
        goal=admission.goal,
        mandate=admission.mandate,
        procedure=admission.procedure,
        charters=tuple(dict.fromkeys(row.child.charter for row in slots)),
        children=tuple(row.child for row in slots),
        verification=tuple(row.verification for row in slots if row.verification is not None),
        plan=WorkPlan(
            company_id=admission.company_id,
            plan_id=admission.plan_id,
            goal_id=admission.goal.goal_id,
            revision=2,
            items=tuple(row.work for row in slots),
        ),
    )


def _slot_abi(admission: StockFlowCycleAdmission, slot: StockFlowCycleSlot, index: int) -> None:
    workflow, profile, tool, models = _ROLE_ABI[index]
    bound = slot.child.binding
    if (
        bound.workflow_name,
        bound.workflow_version,
        bound.model_profile,
        bound.model_registry_version,
        slot.tool.tool,
        slot.tool.tool_version,
    ) != (workflow, "v1", profile, admission.registry_revision, tool, "v1"):
        raise ValueError("Cycle role workflow/profile/tool identity differs")
    if slot.child.quota != AttemptQuota(
        model_requests=models, tool_attempts=1, rework_rounds=0, plan_revisions=0
    ):
        raise ValueError("Cycle child lifetime quota differs from its exact role")
    dependencies = tuple(
        admission.slots[row].child.binding.task_id for row in _DEPENDENCIES.get(index, ())
    )
    if slot.work.depends_on != dependencies:
        raise ValueError("Cycle dependency DAG differs from its closed role layout")
    edge = slot.verification
    if index in _CHECKS:
        author = admission.slots[index - 1].child.binding
        if (
            edge is None
            or (edge.author_task_id, edge.verifier_task_id, edge.check_recipe)
            != (author.task_id, bound.task_id, _CHECKS[index])
            or author.actor_id == bound.actor_id
        ):
            raise ValueError("Cycle verifier edge or independent actor differs")
    elif edge is not None:
        raise ValueError("Cycle author/sender cannot declare another verification edge")
    if index in (2, 3) and slot.work.acceptance != NATIVE_CRITERIA:
        raise ValueError("Cycle native role requires all seven original engineering criteria")
    if index in (8, 9) and slot.work.acceptance != REPORT_CHECK_CRITERIA:
        raise ValueError("Cycle report role requires the existing exact mechanical criteria")


def validate_stockflow_cycle(
    admission: StockFlowCycleAdmission | None,
    registry: ModelRegistry,
    payload: PlanPayload,
) -> StockFlowCycleSelection | None:
    """None means absent config only; a configured mismatch always raises and never falls back."""
    if admission is None:
        return None
    checked = validate_stockflow_cycle_configuration(admission, registry)
    require_exact_cycle_quota(payload.procedure.quota)
    for child in payload.children:
        require_exact_cycle_quota(child.quota)
    actual = PlanPayload.model_validate(payload.model_dump(warnings=False))
    if actual.plan.revision not in (1, 2):
        raise ValueError("Cycle plan stage/revision is outside its bounded occurrence")
    slots = checked.slots[:2] if actual.plan.revision == 1 else checked.slots
    if (
        (actual.company_id, actual.goal, actual.mandate, actual.procedure)
        != (checked.company_id, checked.goal, checked.mandate, checked.procedure)
        or actual.plan.plan_id != checked.plan_id
        or actual.children != tuple(row.child for row in slots)
        or actual.plan.items != tuple(row.work for row in slots)
        or actual.charters != tuple(dict.fromkeys(row.child.charter for row in slots))
        or actual.verification
        != tuple(row.verification for row in slots if row.verification is not None)
    ):
        raise ValueError("Configured cycle does not match the complete permanent plan layout")
    full = actual.plan.revision == 2
    return StockFlowCycleSelection(
        stage="full" if full else "strategy",
        goal_id=checked.goal.goal_id,
        plan_id=checked.plan_id,
        procedure_id=checked.procedure.procedure_id,
        task_ids=tuple(row.child.binding.task_id for row in slots),
        native_task_ids=tuple(row.child.binding.task_id for row in checked.slots[2:4])
        if full
        else (),
        sender_task_id=checked.slots[-1].child.binding.task_id if full else None,
    )
