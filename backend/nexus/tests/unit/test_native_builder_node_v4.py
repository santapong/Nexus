"""Opt-in v4 preserves historical pins/recipe and adds no private execution authority."""

import json
from pathlib import Path

import pytest

from nexus.builder.node_contracts import NodeRuntimeInputs
from nexus.builder.node_recipe import recipe_sha256, wrappers
from nexus.builder.node_v4_assets import csv_wrapper_sha256
from nexus.builder.node_v4_recipe import v4_recipe_sha256
from nexus.tests.node_v4_support import v4_inputs


@pytest.mark.parametrize("version", [1, 2, 3])
def test_exact_old_node_pins_roundtrip_without_csv_field(version: int) -> None:
    raw = (Path(__file__).parents[1] / f"fixtures/node-v3-golden/pins-v{version}.json").read_text()
    pins = NodeRuntimeInputs.model_validate_json(raw)
    assert pins.model_dump_json() == raw and "csv_regression" not in pins.model_dump()
    assert pins.recipe == f"nexus.builder.node.v{version}"


def test_default_v3_method_digest_and_all_wrapper_bytes_remain_exact() -> None:
    golden = json.loads(
        (Path(__file__).parents[1] / "fixtures/node-v3-golden/recipe.json").read_text()
    )
    assert (
        recipe_sha256()
        == golden["v3_recipe_sha256"]
        == "15bb7b99c9d1fc13f01250515485a0e8807c138c1df56f28a601d6c3043ff189"
    )
    assert wrappers() == golden["wrappers"]
    assert v4_recipe_sha256() != recipe_sha256()


def test_only_explicit_v4_has_mandatory_complete_csv_pin_object() -> None:
    value = v4_inputs()
    assert value.recipe == "nexus.builder.node.v4"
    assert (
        value.csv_regression is not None
        and value.csv_regression.wrapper_sha256 == csv_wrapper_sha256()
    )
    with pytest.raises(ValueError):
        NodeRuntimeInputs.model_validate_json(
            value.model_copy(update={"csv_regression": None}).model_dump_json()
        )
    with pytest.raises(ValueError):
        NodeRuntimeInputs.model_validate_json(
            value.model_copy(update={"recipe": "nexus.builder.node.v3"}).model_dump_json()
        )


@pytest.mark.parametrize(
    "field", ["wrapper_sha256", "mapping_sha256", "command_recipe_sha256", "commands", "policy"]
)
def test_v4_partial_or_unreviewed_recipe_is_rejected(field: str) -> None:
    from nexus.builder.node_recipe import require_node_recipe
    from nexus.tests.node_v4_support import described_v4_check

    value = described_v4_check()
    spec, policy = value.author.spec, value.declaration.policy
    assert spec.runtime_inputs is not None and spec.runtime_inputs.csv_regression is not None
    runtime = spec.runtime_inputs
    if field in {"wrapper_sha256", "mapping_sha256"}:
        csv = spec.runtime_inputs.csv_regression.model_copy(update={field: "a" * 64})
        spec = spec.model_copy(
            update={
                "runtime_inputs": spec.runtime_inputs.model_copy(update={"csv_regression": csv})
            }
        )
    if field == "command_recipe_sha256":
        spec = spec.model_copy(
            update={"runtime_inputs": runtime.model_copy(update={field: "a" * 64})}
        )
    if field == "policy":
        policy = policy.model_copy(update={"runtime_inputs": None})
    if field == "commands":
        spec = spec.model_copy(
            update={"job": spec.job.model_copy(update={"commands": spec.job.commands[:4]})}
        )
    with pytest.raises(ValueError):
        require_node_recipe(spec, policy, execution=True)


def test_v4_same_transition_keeps_baseline_only_failure_without_losing_actual_commands() -> None:
    from nexus.builder.node_capture import node_capture_result
    from nexus.tests.node_v4_support import described_v4_check
    from nexus.tests.unit.test_company_foundation import proposal
    from nexus.tests.unit.test_native_builder_node_capture import frame

    spec = described_v4_check().author.spec
    result = node_capture_result(
        frame(), spec, proposal(), 1, "1" * 64, "nexus-builder-" + "d" * 32
    )
    assert result.outcome == "commands_failed" and len(result.commands) == 4
    assert "phase_cleanup_failed" in result.limitations
