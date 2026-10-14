"""Finite Node recipe preserves baseline stop and every neighboring sandbox boundary."""

from pathlib import Path

import pytest

from nexus.builder.contracts import BuilderCapabilities
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.node_recipe import (
    LEGACY_RECIPE_SHA256,
    command_policies,
    command_references,
    node_script,
    require_node_recipe,
)
from nexus.builder.node_runtime_plan import node_argv
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.runtime_plan import PreparedSources, runtime_argv
from nexus.company.management.canonical import canonical_sha256
from nexus.tests.node_input_support import configured_inputs
from nexus.tests.unit.test_native_builder_node_inputs import original


def configured(tmp_path: Path) -> tuple[BuilderToolPolicy, BuilderExecutionSpec]:
    policy, spec, _ = original()
    pins = configured_inputs(tmp_path).pins
    policy = policy.model_copy(update={"commands": command_policies(), "runtime_inputs": pins})
    spec = spec.model_copy(
        update={
            "runtime_inputs": pins,
            "policy_sha256": canonical_sha256(policy),
            "job": spec.job.model_copy(update={"commands": command_references()}),
        }
    )
    return policy, spec


def test_node_recipe_requires_complete_baseline_and_post_not_arbitrary_subset(
    tmp_path: Path,
) -> None:
    policy, spec = configured(tmp_path)
    script = node_script(spec, policy)
    assert 'if test "$code" -ne 0' in script
    assert "cp -R /source/baseline /scratch/work/baseline" in script
    assert "cd /scratch/work/post" in script and "--offline" not in script
    shortened = spec.model_copy(
        update={"job": spec.job.model_copy(update={"commands": spec.job.commands[1:]})}
    )
    with pytest.raises(ValueError, match="complete ordered"):
        node_script(shortened, policy)


def test_exact_v1_recipe_is_recovery_only_and_wrong_version_hash_is_denied(tmp_path: Path) -> None:
    policy, spec = configured(tmp_path)
    assert spec.runtime_inputs is not None
    legacy = spec.runtime_inputs.model_copy(
        update={
            "recipe": "nexus.builder.node.v1",
            "command_recipe_sha256": LEGACY_RECIPE_SHA256,
        }
    )
    policy = policy.model_copy(update={"runtime_inputs": legacy})
    spec = spec.model_copy(
        update={"runtime_inputs": legacy, "policy_sha256": canonical_sha256(policy)}
    )
    require_node_recipe(spec, policy, execution=False)
    with pytest.raises(ValueError, match="recovery only"):
        node_script(spec, policy)
    wrong = legacy.model_copy(update={"recipe": "nexus.builder.node.v2"})
    with pytest.raises(ValueError, match="differs from approved pins"):
        require_node_recipe(
            spec.model_copy(update={"runtime_inputs": wrong}), policy, execution=False
        )


def test_node_mount_exec_only_changes_hard_scratch_and_adds_readonly_pinned_inputs(
    tmp_path: Path,
) -> None:
    config = configured_inputs(tmp_path)
    policy, spec, _ = original()
    policy = policy.model_copy(
        update={"commands": command_policies(), "runtime_inputs": config.pins}
    )
    spec = spec.model_copy(
        update={
            "runtime_inputs": config.pins,
            "policy_sha256": canonical_sha256(policy),
            "job": spec.job.model_copy(
                update={
                    "commands": command_references(),
                    "architecture": "amd64",
                    "source": spec.job.source.model_copy(
                        update={"repository_symbol": policy.repository_symbol}
                    ),
                }
            ),
        }
    )
    base = tmp_path / "job"
    base.mkdir(mode=0o700)
    for name in ("baseline", "post", "node-commands"):
        (base / name).mkdir(mode=0o700)
    for name in ("entrypoint.sh", "resolv.conf", "loopback-hosts"):
        (base / name).write_text("")
    caps = BuilderCapabilities(
        architecture="amd64",
        rootless=True,
        cgroup_v2=True,
        controllers=frozenset({"cpu", "memory", "pids"}),
        hard_workspace_quota=True,
        network_none_verified=True,
        image_present=True,
        qualified_image=policy.image,
    )
    sources = PreparedSources(base / "baseline", base / "post")
    generic = runtime_argv(spec, policy, caps, sources, base / "entrypoint.sh")
    argv = node_argv(spec, policy, caps, sources, base, config)
    assert any(row.startswith("/scratch:rw,nodev,nosuid,noexec,") for row in generic)
    assert any(row.startswith("/scratch:rw,nodev,nosuid,exec,") for row in argv)
    assert any(row.startswith("/outputs:rw,nodev,nosuid,noexec,") for row in argv)
    assert any(row.startswith("/tmp:rw,nodev,nosuid,noexec,") for row in argv)
    assert f"{config.cache}:/cache/store:ro" in argv and f"{config.tools}:/tools:ro" in argv
    assert f"{base / 'loopback-hosts'}:/etc/hosts:ro" in argv
    assert not any(":/etc/hosts:ro" in value for value in generic)
    assert {
        "--network=none",
        "--read-only",
        "--pull=never",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
    } <= set(argv)
