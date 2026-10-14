"""Optional runtime pins preserve historical bytes and bind every new policy/action parameter."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.node_contracts import NodeRuntimeInputs
from nexus.builder.policy import BuilderToolPolicy
from nexus.company.management.canonical import canonical_sha256


def pins() -> NodeRuntimeInputs:
    return NodeRuntimeInputs(
        tool_symbol="pnpm.v9_12",
        cache_symbol="stockflow.pnpm.amd64.v1",
        image_id="1" * 64,
        node_version="22.23.3",
        pnpm_version="9.12.0",
        pnpm_archive_sha256="2" * 64,
        pnpm_integrity="sha512-" + "a" * 86 + "==",
        cache_archive_sha256="3" * 64,
        cache_manifest_sha256="4" * 64,
        lock_sha256="5" * 64,
        command_recipe_sha256="6" * 64,
    )


def original() -> tuple[BuilderToolPolicy, BuilderExecutionSpec, dict[str, str]]:
    value = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "native-builder-codec-v1.json").read_text()
    )
    return (
        BuilderToolPolicy.model_validate_json(value["policy_json"]),
        BuilderExecutionSpec.model_validate_json(value["spec_json"]),
        value,
    )


def test_no_runtime_inputs_keeps_actual_prefield_serialized_bytes_hashes() -> None:
    policy, spec, before = original()
    assert (
        policy.model_dump_json() == before["policy_json"]
        and spec.model_dump_json() == before["spec_json"]
    )
    assert (
        canonical_sha256(policy) == before["policy_canonical_sha"]
        and canonical_sha256(spec) == before["spec_canonical_sha"]
    )
    assert "runtime_inputs" not in spec.model_dump(
        mode="json"
    ) and "runtime_inputs" not in policy.model_dump(mode="json")


def test_amd64_qualified_node_inputs_cannot_claim_arm64() -> None:
    with pytest.raises(ValidationError):
        NodeRuntimeInputs.model_validate({**pins().model_dump(), "architecture": "arm64"})


@pytest.mark.parametrize(
    "field", ["tool_symbol", "cache_archive_sha256", "lock_sha256", "pnpm_archive_sha256"]
)
def test_new_runtime_input_change_invalidates_complete_policy_hash(field: str) -> None:
    policy, spec, _ = original()
    values = pins()
    configured = policy.model_copy(update={"runtime_inputs": values})
    bound = spec.model_copy(
        update={"runtime_inputs": values, "policy_sha256": canonical_sha256(configured)}
    )
    bound.require_policy(configured)
    changed = values.model_copy(
        update={field: "other.tool" if field == "tool_symbol" else "9" * 64}
    )
    with pytest.raises(ValueError):
        bound.require_policy(configured.model_copy(update={"runtime_inputs": changed}))
