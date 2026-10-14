"""Pure mixed-cycle descriptions never confer current execution or proof authority."""

from uuid import UUID

import pytest

from nexus.company.management.cycle_admission import (
    validate_stockflow_cycle,
    validate_stockflow_cycle_configuration,
)
from nexus.company.management.cycle_admission_contracts import (
    StockFlowCycleAdmission,
)
from nexus.company.management.plans import (
    PlanPayload,
)
from nexus.tests.unit.cycle_admission_fixture import cycle


def test_absent_configuration_only_returns_none_without_rewriting_legacy_payload() -> None:
    item = cycle()
    original = item.full.model_dump_json()
    assert validate_stockflow_cycle(None, item.registry, item.full) is None
    assert item.full.model_dump_json() == original


@pytest.mark.parametrize("stage", ["strategy", "full"])
def test_exact_stage_selects_descriptions_without_authority_fields(stage: str) -> None:
    item = cycle()
    payload = item.strategy if stage == "strategy" else item.full
    result = validate_stockflow_cycle(item.admission, item.registry, payload)
    assert result is not None and result.stage == stage
    assert result.task_ids == tuple(child.binding.task_id for child in payload.children)
    assert result.native_task_ids == (() if stage == "strategy" else (UUID(int=202), UUID(int=203)))
    assert set(result.model_dump()) == {
        "stage",
        "goal_id",
        "plan_id",
        "procedure_id",
        "task_ids",
        "native_task_ids",
        "sender_task_id",
    }


@pytest.mark.parametrize("field", ["company_id", "goal", "mandate", "procedure", "plan"])
def test_configured_foreign_binding_raises_instead_of_legacy_fallback(field: str) -> None:
    item = cycle()
    if field == "company_id":
        changed = UUID(int=999)
    else:
        original = getattr(item.full, field)
        key = {
            "goal": "revision_id",
            "mandate": "revision_id",
            "procedure": "procedure_id",
            "plan": "plan_id",
        }[field]
        changed = original.model_copy(update={key: UUID(int=999)})
    with pytest.raises(ValueError):
        validate_stockflow_cycle(
            item.admission, item.registry, item.full.model_copy(update={field: changed})
        )


@pytest.mark.parametrize("field", ["revision", "pricebook_version", "company_id"])
def test_full_registry_identity_must_match_before_role_selection(field: str) -> None:
    item = cycle()
    value = UUID(int=999) if field == "company_id" else "changed"
    with pytest.raises(ValueError):
        validate_stockflow_cycle(
            item.admission, item.registry.model_copy(update={field: value}), item.strategy
        )


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "extra",
        "reorder",
        "crossed_actor",
        "changed_quota",
        "changed_criteria",
        "changed_edge",
        "changed_dependency",
    ],
)
def test_any_changed_full_layout_denies(kind: str) -> None:
    item = cycle()
    data = item.full.model_dump()
    if kind == "missing":
        data["children"] = data["children"][:-1]
        data["plan"]["items"] = data["plan"]["items"][:-1]
    elif kind == "extra":
        child, work = dict(data["children"][-1]), dict(data["plan"]["items"][-1])
        child["binding"] = dict(
            child["binding"], task_id=UUID(int=999), trace_id=UUID(int=998), run_id=UUID(int=997)
        )
        work.update(task_id=UUID(int=999), trace_id=UUID(int=998))
        data["children"] += (child,)
        data["plan"]["items"] += (work,)
    elif kind == "reorder":
        data["children"] = tuple(reversed(data["children"]))
    elif kind == "crossed_actor":
        data["children"][2]["binding"]["actor_id"] = UUID(int=999)
    elif kind == "changed_quota":
        data["children"][2]["quota"]["tool_attempts"] = 0
    elif kind == "changed_criteria":
        data["plan"]["items"][2]["acceptance"] = ("claimed.pass",)
    elif kind == "changed_edge":
        data["verification"][1]["check_recipe"] = "claimed.pass"
    else:
        data["plan"]["items"][4]["depends_on"] = ()
    with pytest.raises(ValueError):
        validate_stockflow_cycle(item.admission, item.registry, PlanPayload.model_validate(data))


@pytest.mark.parametrize("value", [False, True, 0.0, "0"])
@pytest.mark.parametrize("where", ["root", "native", "ordinary"])
def test_raw_quotas_are_not_normalized_by_json_before_validation(value: object, where: str) -> None:
    item = cycle()
    admission = item.admission
    if where == "root":
        quota = admission.procedure.quota.model_copy(update={"model_requests": value})
        admission = admission.model_copy(
            update={"procedure": admission.procedure.model_copy(update={"quota": quota})}
        )
    else:
        index = 2 if where == "native" else 1
        rows = list(admission.slots)
        quota = rows[index].child.quota.model_copy(update={"model_requests": value})
        rows[index] = rows[index].model_copy(
            update={"child": rows[index].child.model_copy(update={"quota": quota})}
        )
        admission = admission.model_copy(update={"slots": tuple(rows)})
    with pytest.raises(ValueError):
        validate_stockflow_cycle(admission, item.registry, item.strategy)


@pytest.mark.parametrize(
    "kind",
    [
        "native_model",
        "root_replenish",
        "ordinary_workflow",
        "native_tool",
        "crossed_verifier",
        "unselected_sender",
    ],
)
def test_complete_configuration_is_checked_even_for_strategy_stage(kind: str) -> None:
    item = cycle()
    data = item.admission.model_dump()
    if kind == "native_model":
        data["slots"][2]["child"]["quota"]["model_requests"] = 1
    elif kind == "root_replenish":
        data["procedure"]["quota"]["model_requests"] = 4
    elif kind == "ordinary_workflow":
        data["slots"][4]["child"]["binding"]["workflow_name"] = "anything"
    elif kind == "native_tool":
        data["slots"][2]["tool"]["tool"] = "model.request.v1"
    elif kind == "crossed_verifier":
        data["slots"][3]["child"]["binding"]["actor_id"] = data["slots"][2]["child"]["binding"][
            "actor_id"
        ]
    else:
        data["slots"][-1]["child"]["binding"]["model_profile"] = "routine"
    with pytest.raises(ValueError):
        validate_stockflow_cycle(
            StockFlowCycleAdmission.model_validate(data), item.registry, item.strategy
        )


def test_extra_authority_fields_are_rejected_by_contract() -> None:
    item = cycle()
    data = item.admission.model_dump() | {"approved": True}
    with pytest.raises(ValueError):
        StockFlowCycleAdmission.model_validate(data)


def test_configuration_validator_works_before_any_derived_registry_or_payload() -> None:
    item = cycle()
    assert validate_stockflow_cycle_configuration(item.admission, item.registry) == item.admission
    derived = item.registry.model_copy(update={"revision": "derived-model-selection"})
    with pytest.raises(ValueError, match="complete original registry"):
        validate_stockflow_cycle_configuration(item.admission, derived)


@pytest.mark.parametrize("revision", [True, 0, 3])
def test_copied_plan_revision_cannot_select_a_different_stage(revision: object) -> None:
    item = cycle()
    copied = item.full.model_copy(
        update={"plan": item.full.plan.model_copy(update={"revision": revision})}
    )
    with pytest.raises(ValueError):
        validate_stockflow_cycle(item.admission, item.registry, copied)


def test_copied_false_nonexecuting_root_is_denied_before_stage_selection() -> None:
    item = cycle()
    copied = item.admission.model_copy(
        update={"procedure": item.admission.procedure.model_copy(update={"non_executing": False})}
    )
    with pytest.raises(ValueError):
        validate_stockflow_cycle_configuration(copied, item.registry)


def test_actual_profile_validation_is_not_replaced_by_pure_match() -> None:
    from nexus.company.management.model_profile_checks import validate_model_profile
    from nexus.company.management.plan_catalog import PlanAdmissionCatalog
    from nexus.tests.unit.test_company_model_registry import NOW

    item = cycle()
    assert validate_stockflow_cycle(item.admission, item.registry, item.strategy) is not None
    catalog = PlanAdmissionCatalog(
        company_id=item.registry.company_id,
        models=item.registry,
        admitted_profiles=frozenset({"reasoning"}),
        check_recipes=frozenset(),
    )
    with pytest.raises(ValueError, match="no current registered model evidence"):
        validate_model_profile(catalog, item.strategy.children[0], NOW)


@pytest.mark.parametrize("kind", ["over32", "duplicate", "duplicate_charter_revision"])
def test_complete_validator_rejects_unselected_full_plan_invariants(kind: str) -> None:
    item = cycle()
    slots = list(item.admission.slots)
    if kind == "duplicate_charter_revision":
        charter = slots[6].child.charter.model_copy(
            update={"revision_id": slots[4].child.charter.revision_id}
        )
        slots[6] = slots[6].model_copy(
            update={"child": slots[6].child.model_copy(update={"charter": charter})}
        )
    else:
        criteria = (
            tuple(f"criterion.{number}.v1" for number in range(33))
            if kind == "over32"
            else ("criterion.same.v1", "criterion.same.v1")
        )
        slots[4] = slots[4].model_copy(
            update={"work": slots[4].work.model_copy(update={"acceptance": criteria})}
        )
    admission = item.admission.model_copy(update={"slots": tuple(slots)})
    with pytest.raises(ValueError):
        validate_stockflow_cycle_configuration(admission, item.registry)
    with pytest.raises(ValueError):
        validate_stockflow_cycle(admission, item.registry, item.strategy)
