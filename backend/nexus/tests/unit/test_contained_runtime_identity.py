"""PhaseA wire/policy/Node compatibility proof only; no runtime configuration or jobs."""

import json
from pathlib import Path

import pytest

from nexus.builder.contained_plan import describe_contained_selectors
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.node_recipe import LEGACY_RECIPE_SHA256, V2_RECIPE_SHA256, recipe_sha256
from nexus.builder.node_v4_assets import csv_wrapper_sha256
from nexus.builder.node_v4_recipe import v4_recipe_sha256, v4_wrappers
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.runtime_identity import RUNTIME_V2, RUNTIME_V2_METHOD_SHA256
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.canonical import canonical_sha256
from nexus.harness.canonical import action_hash
from nexus.tests.node_v4_support import described_v4_check
from nexus.tests.unit.test_native_builder_node_inputs import original

ROOT = Path(__file__).parents[1] / "fixtures/contained-runtime-v1-golden"


def test_frozen_actual_legacy_policy_spec_action_and_all_node_hashes_stay_exact() -> None:
    policy = BuilderToolPolicy.model_validate_json((ROOT / "policy.json").read_bytes())
    spec = BuilderExecutionSpec.model_validate_json((ROOT / "spec.json").read_bytes())
    action = ActionProposal.model_validate_json((ROOT / "action.json").read_bytes())
    assert policy.model_dump_json() == (ROOT / "policy.json").read_text()
    assert spec.model_dump_json() == (ROOT / "spec.json").read_text()
    assert action.model_dump_json() == (ROOT / "action.json").read_text()
    values = json.loads((ROOT / "methods.json").read_bytes())
    assert canonical_sha256(policy) == values["policy_sha256"]
    assert (
        canonical_sha256(spec) == values["spec_sha256"]
        and action_hash(action) == values["action_sha256"]
    )
    assert [LEGACY_RECIPE_SHA256, V2_RECIPE_SHA256, recipe_sha256(), v4_recipe_sha256()] == values[
        "node_recipe_digests"
    ]
    assert (
        v4_wrappers() == values["v4_wrappers"]
        and csv_wrapper_sha256() == values["csv_wrapper_sha256"]
    )
    spec.require_policy(policy)


def configured() -> tuple[BuilderExecutionSpec, BuilderToolPolicy]:
    policy, spec, _ = original()
    policy = BuilderToolPolicy.model_validate_json(
        policy.model_copy(
            update={"runtime_recipe": RUNTIME_V2, "runtime_method_sha256": RUNTIME_V2_METHOD_SHA256}
        ).model_dump_json()
    )
    spec = BuilderExecutionSpec.model_validate_json(
        spec.model_copy(
            update={"runtime_recipe": RUNTIME_V2, "policy_sha256": canonical_sha256(policy)}
        ).model_dump_json()
    )
    return spec, policy


def test_explicit_v2_describes_fixed_selectors_but_existing_execution_denies() -> None:
    spec, policy = configured()
    value = describe_contained_selectors(spec, policy)
    assert value.global_arguments == ("--cgroup-manager=cgroupfs",)
    assert value.run_arguments == ("--cgroups=split",) and value.execution_enabled is False
    with pytest.raises(ValueError, match="not configured"):
        spec.require_policy(policy)
    assert (
        "runtime_recipe" in policy.model_dump() and "runtime_method_sha256" in policy.model_dump()
    )


@pytest.mark.parametrize(
    "version,method",
    [
        ("nexus.builder.runtime.v1", "a" * 64),
        (RUNTIME_V2, None),
        (RUNTIME_V2, "a" * 64),
        ("foreign", RUNTIME_V2_METHOD_SHA256),
        (True, RUNTIME_V2_METHOD_SHA256),
    ],
)
def test_policy_version_method_tuple_is_closed(version: object, method: object) -> None:
    policy, _, _ = original()
    with pytest.raises(ValueError):
        BuilderToolPolicy.model_validate_json(
            policy.model_copy(
                update={"runtime_recipe": version, "runtime_method_sha256": method}
            ).model_dump_json()
        )


@pytest.mark.parametrize("fault", ["version", "method", "policy_sha", "parent", "manager", "split"])
def test_copied_or_arbitrary_selector_descriptions_deny(fault: str) -> None:
    spec, policy = configured()
    if fault == "version":
        spec = spec.model_copy(update={"runtime_recipe": "nexus.builder.runtime.v1"})
    if fault == "method":
        policy = policy.model_copy(update={"runtime_method_sha256": "a" * 64})
    if fault == "policy_sha":
        spec = spec.model_copy(update={"policy_sha256": "a" * 64})
    if fault in {"parent", "manager", "split"}:
        raw = policy.model_dump(mode="json")
        raw[fault] = "/foreign" if fault == "parent" else "other"
        with pytest.raises(ValueError):
            BuilderToolPolicy.model_validate_json(json.dumps(raw))
        return
    with pytest.raises(ValueError):
        describe_contained_selectors(spec, policy)


def test_node_v4_method_has_explicit_description_support_without_asset_hash_change() -> None:
    value = described_v4_check()
    policy = value.declaration.policy
    policy = BuilderToolPolicy.model_validate_json(
        policy.model_copy(
            update={"runtime_recipe": RUNTIME_V2, "runtime_method_sha256": RUNTIME_V2_METHOD_SHA256}
        ).model_dump_json()
    )
    spec = value.author.spec.model_copy(
        update={"runtime_recipe": RUNTIME_V2, "policy_sha256": canonical_sha256(policy)}
    )
    assert describe_contained_selectors(spec, policy).run_arguments == ("--cgroups=split",)
    assert (
        spec.runtime_inputs is not None
        and spec.runtime_inputs.command_recipe_sha256 == v4_recipe_sha256()
    )
    with pytest.raises(ValueError):
        spec.require_policy(policy)


def test_default_node_v3_cannot_silently_select_runtime_v2() -> None:
    from nexus.tests.unit.test_native_builder_node_inputs import pins

    spec, policy = configured()
    node = pins()
    policy = policy.model_copy(update={"runtime_inputs": node})
    spec = spec.model_copy(
        update={"runtime_inputs": node, "policy_sha256": canonical_sha256(policy)}
    )
    with pytest.raises(ValueError):
        describe_contained_selectors(spec, policy)


def test_old_runtime_renderer_denies_v2_before_paths_or_capability_io() -> None:
    from nexus.builder.runtime_plan import PreparedSources, runtime_argv
    from nexus.tests.builder_support import synthetic_capabilities

    spec, policy = configured()
    with pytest.raises(ValueError, match="not configured"):
        runtime_argv(
            spec,
            policy,
            synthetic_capabilities(),
            PreparedSources(Path("/missing/baseline"), Path("/missing/post")),
            Path("/missing/entrypoint.sh"),
        )


async def test_existing_native_runner_denies_unconfigured_v2_before_store_prepare_or_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    from typing import cast
    from unittest.mock import AsyncMock

    import nexus.builder.runner as module
    from nexus.builder.runner import NativeBuilderRunner
    from nexus.builder.source_guard import BuilderSourceGuard
    from nexus.company.access import VerifiedIdentity
    from nexus.tests.builder_support import described_binding

    spec, policy = configured()
    action, lease, _ = described_binding(spec.job)
    identity = VerifiedIdentity(principal_id=lease.actor_id, workspace_id=lease.workspace_id)
    guard = cast(
        BuilderSourceGuard,
        SimpleNamespace(spec=spec, policy=policy, identity=identity, lease=lease),
    )
    runner = NativeBuilderRunner.__new__(NativeBuilderRunner)
    runner.policy = policy
    runner.publisher = None
    actual = AsyncMock()
    prepare = AsyncMock()
    invoke = AsyncMock()
    monkeypatch.setattr(module, "actual_action", actual)
    monkeypatch.setattr(runner, "prepare", prepare)
    monkeypatch.setattr(runner, "invoke", invoke)
    with pytest.raises(ValueError, match="not configured"):
        await runner.run(lease, identity, action, spec, guard)
    assert actual.await_count == prepare.await_count == invoke.await_count == 0


@pytest.mark.parametrize(
    "global_args,run_args",
    [
        ((), ("--cgroups=split",)),
        (("--cgroup-manager=cgroupfs",), ()),
        (("--cgroup-manager=systemd",), ("--cgroups=split",)),
        (("--cgroup-manager=cgroupfs", "--cgroup-parent=/outside"), ("--cgroups=split",)),
    ],
)
def test_closed_selector_result_has_only_the_fixed_singletons(
    global_args: tuple[str, ...], run_args: tuple[str, ...]
) -> None:
    from nexus.builder.contained_plan import ContainedSelectorDescription

    with pytest.raises(ValueError):
        ContainedSelectorDescription(global_arguments=global_args, run_arguments=run_args)
