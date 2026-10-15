"""Closed template data and full Node/CSV pins; old runtime wire stays unchanged."""

from dataclasses import replace

import pytest

from nexus.builder.csv_report_contracts import CsvRegressionPins
from nexus.builder.node_contracts import NodeRuntimeInputs
from nexus.builder.selected_strategy_contracts import SelectedBuilderTemplate
from nexus.tests.unit.selected_strategy_pins_fixture import selected_case
from nexus.tests.unit.test_native_builder_node_inputs import original


@pytest.mark.parametrize("field", list(NodeRuntimeInputs.model_fields))
def test_every_runtime_input_is_pinned(field: str) -> None:
    case = selected_case()
    inputs = case.template.runtime_inputs
    value = (
        None
        if field == "csv_regression"
        else "other"
        if field
        in {
            "recipe",
            "tool_symbol",
            "cache_symbol",
            "architecture",
            "node_version",
            "pnpm_version",
            "pnpm_integrity",
        }
        else "f" * 64
    )
    changed = inputs.model_copy(update={field: value})
    with pytest.raises(ValueError):
        replace(case, spec=case.spec.model_copy(update={"runtime_inputs": changed})).check()


@pytest.mark.parametrize("field", list(CsvRegressionPins.model_fields))
def test_every_csv_hash_method_and_inventory_pin_is_exact(field: str) -> None:
    case = selected_case()
    inputs = case.template.runtime_inputs
    assert inputs.csv_regression is not None
    value = (
        ("other.test.ts",)
        if field.endswith("_files")
        else "other-version"
        if field in {"schema_version", "reporter_version"}
        else "f" * 64
    )
    csv = inputs.csv_regression.model_copy(update={field: value})
    changed = inputs.model_copy(update={"csv_regression": csv})
    with pytest.raises(ValueError):
        replace(case, spec=case.spec.model_copy(update={"runtime_inputs": changed})).check()


def test_unselected_malformed_candidate_also_denies() -> None:
    case = selected_case()
    other = case.candidate_policy.candidates[1].model_copy(update={"patch_sha256": "f" * 64})
    policy = case.candidate_policy.model_copy(update={"candidates": (case.candidate, other)})
    with pytest.raises(ValueError):
        replace(case, candidate_policy=policy).check()


def test_defer_cannot_be_described_as_an_execution() -> None:
    case = selected_case()
    with pytest.raises(ValueError):
        replace(case, candidate=case.candidate_policy.candidates[1]).check()


def test_unknown_template_fields_and_missing_runtime_inputs_deny() -> None:
    template = selected_case().template
    with pytest.raises(ValueError):
        SelectedBuilderTemplate.model_validate(template.model_dump() | {"authority": True})
    with pytest.raises(ValueError):
        SelectedBuilderTemplate.model_validate(template.model_dump(exclude={"runtime_inputs"}))


def test_legacy_v1_original_wire_is_unchanged_and_not_a_selected_execution() -> None:
    policy, spec, golden = original()
    assert policy.model_dump_json() == golden["policy_json"]
    assert spec.model_dump_json() == golden["spec_json"]
    case = selected_case()
    with pytest.raises(ValueError):
        replace(case, policy=policy, spec=spec).check()
    assert policy.model_dump_json() == golden["policy_json"]
    assert spec.model_dump_json() == golden["spec_json"]
