"""Closed v2 compiler descriptions do not enable execution or alter original spec identity."""

from pathlib import Path

import pytest

from nexus.builder.contained_compiler import described_contained_argv, described_contained_script
from nexus.builder.runtime_identity import RUNTIME_V1, RUNTIME_V2, RUNTIME_V2_METHOD_SHA256
from nexus.builder.runtime_plan import PreparedSources, runtime_argv, runtime_script
from nexus.company.management.canonical import canonical_sha256
from nexus.tests.builder_support import synthetic_capabilities
from nexus.tests.node_v4_support import described_v4_check
from nexus.tests.unit.test_contained_runtime_identity import configured
from nexus.tests.unit.test_native_builder_node_inputs import pins


def test_fixed_v2_script_reuses_exact_commands_without_changing_original_hash() -> None:
    spec, policy = configured()
    before = canonical_sha256(spec)
    script = described_contained_script(spec, policy)
    assert script.startswith("#!/bin/sh") and "NEXUS-BUILDER/1" in script
    assert canonical_sha256(spec) == before
    with pytest.raises(ValueError, match="not configured"):
        spec.require_policy(policy)


def test_generic_compiler_adds_only_fixed_selectors_to_existing_exact_argv(tmp_path: Path) -> None:
    spec, policy = configured()
    # This fixture tests actual mount-path validation; HOME mounts are forbidden.
    if str(tmp_path).startswith("/home/"):
        pytest.skip("Use task-owned /tmp basetemp for sandbox path description")
    base = tmp_path / "job"
    base.mkdir()
    for name in ["baseline", "post"]:
        (base / name).mkdir()
    entry = base / "entrypoint.sh"
    entry.write_text("synthetic")
    (base / "resolv.conf").write_text("")
    caps = synthetic_capabilities().model_copy(update={"qualified_image": policy.image})
    sources = PreparedSources(base / "baseline", base / "post")
    actual = described_contained_argv(spec, policy, caps, sources, entry)
    view_policy = policy.model_copy(
        update={"runtime_recipe": RUNTIME_V1, "runtime_method_sha256": None}
    )
    view_spec = spec.model_copy(
        update={"runtime_recipe": RUNTIME_V1, "policy_sha256": canonical_sha256(view_policy)}
    )
    original = runtime_argv(view_spec, view_policy, caps, sources, entry)
    assert actual == (
        *original[:2],
        "--cgroup-manager=cgroupfs",
        *original[2:3],
        "--cgroups=split",
        *original[3:],
    )
    assert described_contained_script(spec, policy) == runtime_script(view_spec, view_policy)


def test_foreign_policy_hash_denies_description_before_mount_access() -> None:
    spec, policy = configured()
    with pytest.raises(ValueError):
        described_contained_script(spec.model_copy(update={"policy_sha256": "0" * 64}), policy)


def test_exact_node_v4_description_retains_script_recipe_and_requires_configured_inputs() -> None:
    item = described_v4_check()
    policy = item.declaration.policy.model_copy(
        update={
            "runtime_recipe": RUNTIME_V2,
            "runtime_method_sha256": RUNTIME_V2_METHOD_SHA256,
        }
    )
    spec = item.author.spec.model_copy(
        update={
            "runtime_recipe": RUNTIME_V2,
            "policy_sha256": canonical_sha256(policy),
        }
    )
    script = described_contained_script(spec, policy)
    assert "/scratch/work/baseline" in script and "/node-commands/phase-cleanup.py" in script
    with pytest.raises(ValueError, match="configured inputs"):
        described_contained_argv(
            spec,
            policy,
            synthetic_capabilities(),
            PreparedSources(Path("/missing/base"), Path("/missing/post")),
            Path("/missing/entrypoint.sh"),
        )
    with pytest.raises(ValueError, match="entrypoint"):
        described_contained_argv(
            spec,
            policy,
            synthetic_capabilities(),
            PreparedSources(Path("/missing/base"), Path("/missing/post")),
            Path("/missing/other.sh"),
        )
    legacy = pins()
    changed_policy = policy.model_copy(update={"runtime_inputs": legacy})
    changed = spec.model_copy(
        update={
            "runtime_inputs": legacy,
            "policy_sha256": canonical_sha256(changed_policy),
        }
    )
    with pytest.raises(ValueError, match="Node v4"):
        described_contained_script(changed, changed_policy)
