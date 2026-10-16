"""Closed coding descriptions only; no current registration, model or native execution proof."""

from decimal import Decimal
from typing import Literal, cast
from uuid import uuid5

import pytest

from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import REPORT_CHECK_CRITERIA
from nexus.company.management.native_execution_profiles import NATIVE_CRITERIA
from nexus.company.management.nexus_coding_admission import (
    NEXUS_CODING_ROLES,
    NexusCodingAdmission,
    NexusCodingSlot,
    select_nexus_coding_plan,
)
from nexus.company.management.nexus_cycle_admission import NexusCycleAdmission, NexusCycleSlot
from nexus.company.management.planning_origin_contracts import PlanningOriginRef
from nexus.company.management.plans import PlanPayload
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.harness.standing_contracts import ToolPermission
from nexus.tests.unit.nexus_cycle_fixture import case, key, origin


def admission() -> NexusCodingAdmission:
    """Synthetic complete family; constructing a description admits no real work.

    Cohesion exception: the complete ten-slot fixture keeps all declared identity,
    quota and graph inputs together so negatives cannot omit a hidden dependency.
    """
    old, _ = case()
    root_binding = old.procedure.binding.model_copy(
        update={
            "task_id": key("coding-root-task"),
            "trace_id": key("coding-root-trace"),
            "run_id": key("coding-root-run"),
            "workflow_name": "nexus.coding-cycle.v1",
        }
    )
    procedure = old.procedure.model_copy(
        update={
            "procedure_id": key("coding-procedure"),
            "binding": root_binding,
            "allocation_usd": Decimal("2"),
            "quota": AttemptQuota(
                model_requests=5, tool_attempts=5, rework_rounds=0, plan_revisions=1
            ),
        }
    )
    model_roles = ("planner", "coder", "strategy", "presentation", "support")
    model_profiles = ("reasoning", "engineering", "reasoning", "routine", "routine")
    workflows = (
        "company.planning.v1",
        "company.coding.v1",
        "company.strategy.v1",
        "company.presentation.v1",
        "company.support.v1",
    )
    native: dict[str, NexusCycleSlot] = {row.role: row for row in old.slots}
    slots = []
    for index, role in enumerate(NEXUS_CODING_ROLES):
        template = native[role if index >= 5 else "planner"]
        binding = template.child.binding.model_copy(
            update={
                "task_id": key("coding-" + role + "-task"),
                "trace_id": key("coding-" + role + "-trace"),
                "run_id": key("coding-" + role + "-run"),
                "actor_id": root_binding.actor_id
                if role == "sender"
                else key("coding-" + role + "-actor"),
                **(
                    {
                        "workflow_name": workflows[index],
                        "model_profile": model_profiles[index],
                    }
                    if index < 5
                    else {}
                ),
            }
        )
        child = template.child.model_copy(
            update={
                "binding": binding,
                "allocation_usd": Decimal(".1"),
                "quota": AttemptQuota(
                    model_requests=int(role in model_roles),
                    tool_attempts=int(role not in model_roles),
                    rework_rounds=0,
                    plan_revisions=0,
                ),
            }
        )
        dependencies = (
            (key("coding-engineering-task"),)
            if role == "report"
            else (key("coding-report-task"),)
            if role == "sender"
            else ()
        )
        work = template.work.model_copy(
            update={
                "task_id": binding.task_id,
                "trace_id": binding.trace_id,
                "department": role,
                "title": "Synthetic Nexus " + role,
                "budget_usd": child.allocation_usd,
                "depends_on": dependencies,
            }
        )
        tool = (
            ToolPermission(
                tool="model.request.v1", tool_version="v1", resource="model:synthetic-nexus-" + role
            )
            if index < 5
            else template.tool
        )
        slots.append(NexusCodingSlot(role=role, child=child, work=work, tool=tool))
    return NexusCodingAdmission(
        kind="nexus.coding-cycle.v1",
        company_id=old.company_id,
        goal=old.goal,
        mandate=old.mandate,
        plan_id=key("coding-plan"),
        registry_revision=old.registry_revision,
        registry_sha256=old.registry_sha256,
        procedure=procedure,
        slots=tuple(slots),
    )


def planning_origin(value: NexusCodingAdmission) -> PlanningOriginRef:
    old, _ = case()
    first = value.payload("planning")
    return origin(old).model_copy(
        update={
            "goal": value.goal,
            "source_plan_id": value.plan_id,
            "source_plan_revision_id": uuid5(value.plan_id, "plan:1:" + canonical_sha256(first)),
            "task_id": value.slots[0].work.task_id,
        }
    )


def test_full_company_family_is_reserved_before_l_only_bootstrap() -> None:
    value = admission()
    first = value.payload("planning")
    full = value.payload("execution", origin=planning_origin(value))
    assert tuple(row.role for row in value.slots) == NEXUS_CODING_ROLES
    assert first.procedure == full.procedure == value.procedure
    assert first.coding_admission_sha256 == full.coding_admission_sha256 == canonical_sha256(value)
    assert len(first.children) == 1 and first.children[0] == value.slots[0].child
    assert len(full.children) == 10 and not first.verification
    assert (
        sum(row.child.quota.model_requests for row in value.slots),
        sum(row.child.quota.tool_attempts for row in value.slots),
    ) == (5, 5)
    assert full.plan.items[5].acceptance == full.plan.items[6].acceptance == NATIVE_CRITERIA
    assert full.plan.items[7].acceptance == full.plan.items[8].acceptance == REPORT_CHECK_CRITERIA
    assert full.plan.items[5].depends_on == full.plan.items[6].depends_on == ()
    assert full.plan.items[7].depends_on == (full.plan.items[5].task_id,)
    assert full.plan.items[9].depends_on == (full.plan.items[7].task_id,)
    assert select_nexus_coding_plan(value, first) == "planning"
    assert select_nexus_coding_plan(value, full) == "execution"
    assert NexusCodingAdmission.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "reordered",
        "kind",
        "kind-absent",
        "root-model",
        "root-tool",
        "root-revision",
        "root-workflow",
        "root-profile",
        "root-registry",
        "usd",
        "workspace",
        "company",
        "goal",
        "task",
        "trace",
        "run",
        "coder-owner",
        "ev-coder",
        "ev-engineer",
        "rv-author",
        "sender-owner",
        "child-model",
        "native-model",
        "child-tool",
        "child-rework",
        "child-revision",
        "boolean-quota",
        "work-usd",
        "criteria",
        "report-criteria",
        "model-criteria",
        "dependency",
        "verifier-dependency",
        "workflow",
        "profile",
        "tool",
        "model-resource",
    ],
)
def test_closed_family_denies_identity_spend_abi_and_graph_escape(fault: str) -> None:
    """Cohesion exception: each paired raw mutation exercises the same full frozen family."""
    data = admission().model_dump()
    slots, root = data["slots"], data["procedure"]
    if fault == "missing":
        data["slots"] = slots[:-1]
    elif fault == "reordered":
        data["slots"] = (slots[1], slots[0], *slots[2:])
    elif fault == "kind":
        data["kind"] = "nexus.coding-cycle.v2"
    elif fault == "kind-absent":
        del data["kind"]
    elif fault.startswith("root-"):
        if fault in {"root-model", "root-tool", "root-revision"}:
            root["quota"][
                {
                    "root-model": "model_requests",
                    "root-tool": "tool_attempts",
                    "root-revision": "plan_revisions",
                }[fault]
            ] = 0
        else:
            root["binding"][
                {
                    "root-workflow": "workflow_name",
                    "root-profile": "model_profile",
                    "root-registry": "model_registry_version",
                }[fault]
            ] = "wrong"
    elif fault == "usd":
        root["allocation_usd"] = Decimal(".5")
    elif fault in {"workspace", "company", "goal", "task", "trace", "run"}:
        if fault == "goal":
            slots[1]["work"]["goal_id"] = key("foreign-goal")
        elif fault == "company":
            slots[1]["child"]["company_id"] = key("foreign-company")
        else:
            name = "workspace_id" if fault == "workspace" else fault + "_id"
            slots[1]["child"]["binding"][name] = (
                key("foreign-workspace") if fault == "workspace" else root["binding"][name]
            )
            if fault in {"task", "trace"}:
                slots[1]["work"][name] = root["binding"][name]
    elif fault in {"coder-owner", "ev-coder", "ev-engineer", "rv-author", "sender-owner"}:
        index, actor = {
            "coder-owner": (1, root["binding"]["actor_id"]),
            "ev-coder": (6, slots[1]["child"]["binding"]["actor_id"]),
            "ev-engineer": (6, slots[5]["child"]["binding"]["actor_id"]),
            "rv-author": (8, slots[7]["child"]["binding"]["actor_id"]),
            "sender-owner": (9, key("not-owner")),
        }[fault]
        slots[index]["child"]["binding"]["actor_id"] = actor
    elif fault in {
        "child-model",
        "native-model",
        "child-tool",
        "child-rework",
        "child-revision",
        "boolean-quota",
    }:
        index = 5 if fault == "native-model" else 1
        field = {
            "child-model": "model_requests",
            "native-model": "model_requests",
            "child-tool": "tool_attempts",
            "child-rework": "rework_rounds",
            "child-revision": "plan_revisions",
            "boolean-quota": "model_requests",
        }[fault]
        slots[index]["child"]["quota"][field] = True if fault == "boolean-quota" else 2
    elif fault == "work-usd":
        slots[1]["work"]["budget_usd"] = Decimal(".2")
    elif fault in {"criteria", "report-criteria"}:
        slots[5 if fault == "criteria" else 7]["work"]["acceptance"] = ("invented.pass",)
    elif fault == "model-criteria":
        slots[1]["work"]["acceptance"] = ("duplicate", "duplicate")
    elif fault in {"dependency", "verifier-dependency"}:
        slots[5 if fault == "dependency" else 6]["work"]["depends_on"] = (
            slots[1]["work"]["task_id"],
        )
    elif fault == "model-resource":
        slots[1]["tool"]["resource"] = "arbitrary:resource"
    elif fault == "tool":
        slots[1]["tool"]["tool"] = "company.builder.run.v1"
    else:
        slots[1]["child"]["binding"][
            "workflow_name" if fault == "workflow" else "model_profile"
        ] = "wrong"
    with pytest.raises(ValueError):
        NexusCodingAdmission.model_validate(data)


@pytest.mark.parametrize(
    "fault",
    [
        "root",
        "quota",
        "criteria",
        "edge",
        "revision",
        "origin",
        "origin-plan",
        "origin-task",
        "origin-head",
        "planner-title",
    ],
)
def test_selection_rejects_changed_frozen_template_without_claiming_database_state(
    fault: str,
) -> None:
    value = admission()
    data = value.payload("execution", origin=planning_origin(value)).model_dump()
    if fault == "root":
        data["procedure"]["procedure_id"] = key("replacement-root")
    elif fault == "quota":
        data["children"][1]["quota"]["model_requests"] = 2
    elif fault == "criteria":
        data["plan"]["items"][1]["acceptance"] = ("changed-authority",)
    elif fault == "edge":
        data["verification"] = ()
    elif fault == "revision":
        data["plan"]["revision"] = 3
    elif fault == "origin":
        data["planning_origin"] = None
    elif fault == "planner-title":
        data["plan"]["items"][0]["title"] = "Replaced registered planner"
    else:
        data["planning_origin"][
            {
                "origin-plan": "source_plan_id",
                "origin-task": "task_id",
                "origin-head": "source_plan_revision_id",
            }[fault]
        ] = key("wrong-origin")
    with pytest.raises(ValueError):
        select_nexus_coding_plan(value, PlanPayload.model_validate(data))


def test_copied_raw_quota_is_checked_before_json_can_normalize_it() -> None:
    value = admission()
    child = value.slots[1].child
    changed = child.model_copy(
        update={"quota": child.quota.model_copy(update={"model_requests": True})}
    )
    slots = (value.slots[0], value.slots[1].model_copy(update={"child": changed}), *value.slots[2:])
    copied = value.model_copy(update={"slots": slots})
    with pytest.raises(ValueError):
        copied.payload("planning")


def test_only_non_planner_titles_are_nonauthority_metadata() -> None:
    value = admission()
    full = value.payload("execution", origin=planning_origin(value))
    items = (
        full.plan.items[0],
        full.plan.items[1].model_copy(update={"title": "A proposed coding task"}),
        *full.plan.items[2:],
    )
    assert (
        select_nexus_coding_plan(
            value,
            full.model_copy(
                update={
                    "plan": full.plan.model_copy(update={"items": items}),
                }
            ),
        )
        == "execution"
    )


def test_old_six_slot_profile_remains_separate_and_frozen() -> None:
    old, _ = case()
    new = admission()
    with pytest.raises(ValueError):
        NexusCodingAdmission.model_validate(old.model_dump())
    with pytest.raises(ValueError):
        NexusCycleAdmission.model_validate(new.model_dump())
    with pytest.raises(ValueError):
        new.payload(cast(Literal["planning", "execution"], "other"))
    with pytest.raises(ValueError):
        new.__setattr__("kind", "nexus.coding-cycle.v1")
