"""Closed two-head structural boundary; these synthetic declarations grant no authority."""

import pytest

from nexus.company.management.native_execution_profiles import require_native_plan
from nexus.company.notifications.native_profile_checks import require_notification_plan
from nexus.tests.unit.nexus_cycle_fixture import case, origin


def test_configured_nexus_mixed_layout_retains_planner_without_zeroing_root() -> None:
    admission, catalog = case()
    require_native_plan(catalog, admission.payload("execution", origin=origin(admission)))
    require_notification_plan(catalog, admission.payload("execution", origin=origin(admission)))


def test_bootstrap_is_one_planner_under_same_future_root_without_native_rows() -> None:
    from nexus.company.management.nexus_cycle_admission import select_nexus_plan

    admission, catalog = case()
    initial = admission.payload("planning")
    assert select_nexus_plan(admission, catalog, initial) == "planning"
    assert initial.procedure == admission.payload("execution", origin=origin(admission)).procedure
    assert len(initial.children) == 1 and not initial.verification
    require_native_plan(catalog, initial)
    require_notification_plan(catalog, initial)
    assert (
        "nexus_cycle_admission"
        not in catalog.model_copy(update={"nexus_cycle_admission": None}).model_dump_json()
    )


@pytest.mark.parametrize(
    "fault",
    [
        "root",
        "planner",
        "native-model",
        "criteria",
        "edge",
        "dependency",
        "revision",
        "origin",
        "title-authority",
    ],
)
def test_closed_layout_denies_rebound_authority_or_other_heads(fault: str) -> None:
    from nexus.company.management.nexus_cycle_admission import select_nexus_plan
    from nexus.execution.runtime_contracts import AttemptQuota
    from nexus.tests.unit.nexus_cycle_fixture import key

    admission, catalog = case()
    payload = admission.payload("execution", origin=origin(admission))
    if fault == "root":
        payload = payload.model_copy(
            update={
                "procedure": payload.procedure.model_copy(
                    update={"allocation_usd": payload.procedure.allocation_usd * 2}
                )
            }
        )
    elif fault in {"planner", "native-model"}:
        index = 0 if fault == "planner" else 1
        children = list(payload.children)
        children[index] = children[index].model_copy(
            update={
                "quota": AttemptQuota(
                    model_requests=2, tool_attempts=1, rework_rounds=0, plan_revisions=0
                )
            }
        )
        payload = payload.model_copy(update={"children": tuple(children)})
    elif fault == "edge":
        payload = payload.model_copy(update={"verification": ()})
    elif fault == "revision":
        payload = payload.model_copy(
            update={"plan": payload.plan.model_copy(update={"revision": 3})}
        )
    elif fault == "origin":
        payload = payload.model_copy(update={"planning_origin": None})
    else:
        items = list(payload.plan.items)
        index = 0 if fault == "title-authority" else 1
        changes = (
            {"acceptance": ("invented.accepted",)}
            if fault == "criteria"
            else {"depends_on": (key("planner-task"),)}
            if fault == "dependency"
            else {"title": "Changed already-registered planner"}
        )
        items[index] = items[index].model_copy(update=changes)
        payload = payload.model_copy(
            update={"plan": payload.plan.model_copy(update={"items": tuple(items)})}
        )
    with pytest.raises(ValueError):
        select_nexus_plan(admission, catalog, payload)


def test_closed_mapper_preserves_planner_and_uses_server_native_criteria_and_edges() -> None:
    from nexus.company.management.canonical import canonical_sha256
    from nexus.company.management.planning_content import PlanningContent, PlanningTask
    from nexus.company.management.planning_proposal_bridge import (
        PlanningProposalTemplate,
        PlanningTaskSlot,
        map_content,
    )
    from nexus.tests.unit.nexus_cycle_fixture import base

    admission, catalog = case()
    template = PlanningProposalTemplate(
        base_plan=base(admission),
        revision="nexus-mapping-v1",
        nexus_admission=admission,
        slots=tuple(
            PlanningTaskSlot(
                key=slot.role,
                allocation=slot.child,
                department=slot.work.department,
                required_dependencies=slot.work.depends_on,
            )
            for slot in admission.slots[1:]
        ),
    )
    content = PlanningContent(
        tasks=tuple(
            PlanningTask(
                key=slot.role,
                title="Review " + slot.role,
                description="Synthetic proposed Nexus work",
                acceptance=("model words are not criteria",),
                depends_on=(),
                evidence_ids=(),
            )
            for slot in admission.slots[1:]
        ),
        questions=(),
    )
    ref = origin(admission).model_copy(
        update={
            "content_sha256": canonical_sha256(content),
            "mapping_sha256": canonical_sha256(template),
        }
    )
    mapped = map_content(content, ref, template)
    assert mapped.procedure == template.base_plan.payload.procedure
    assert mapped.plan.items[0] == template.base_plan.payload.plan.items[0]
    assert mapped.verification == admission.payload("execution", origin=ref).verification
    assert mapped.plan.items[1].acceptance == admission.slots[1].work.acceptance
    require_native_plan(catalog, mapped)
    # A verifier cannot gain an accepted-E dependency that would deadlock its real trigger.
    tasks = list(content.tasks)
    tasks[1] = tasks[1].model_copy(update={"depends_on": ("engineering",)})
    crossed = content.model_copy(update={"tasks": tuple(tasks)})
    with pytest.raises(ValueError):
        map_content(
            crossed, ref.model_copy(update={"content_sha256": canonical_sha256(crossed)}), template
        )
