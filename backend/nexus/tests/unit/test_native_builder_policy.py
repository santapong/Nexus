"""No capability downgrade or arbitrary job/engine command can become a prepared description."""

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nexus.builder.contracts import BuilderCommandReceipt, BuilderJobSpec, BuilderLimits
from nexus.builder.policy import (
    BuilderToolPolicy,
    match_action_lease,
    prepare_podman_argv,
    require_preparation,
)
from nexus.tests.builder_support import (
    described_binding,
    described_job,
    described_policy,
    synthetic_capabilities,
)


@pytest.mark.parametrize(
    "delta",
    [
        {"controllers": frozenset({"cpu", "pids"})},
        {"rootless": False},
        {"hard_workspace_quota": False},
        {"network_none_verified": False},
        {"image_present": False},
        {"architecture": "amd64"},
        {"qualified_image": "different-image"},
    ],
)
def test_unqualified_capability_description_denies(delta: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        require_preparation(
            described_job(), described_policy(), synthetic_capabilities().model_copy(update=delta)
        )


def test_fixed_runtime_argv_disables_pull_proxy_network_and_host_write_mount(
    tmp_path: Path,
) -> None:
    argv = prepare_podman_argv(
        described_job(), described_policy(), synthetic_capabilities(), "unit", tmp_path
    )
    for flag in (
        "--network=none",
        "--pull=never",
        "--http-proxy=false",
        "--read-only",
        "--read-only-tmpfs=false",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
    ):
        assert flag in argv
    assert argv[argv.index("--volume") + 1] == f"{tmp_path}:/workspace:ro"
    assert argv[-2:] == ("pnpm", "test")
    assert "--env-host" not in argv and "--privileged" not in argv


def test_exact_job_action_lease_and_expiry_description() -> None:
    job = described_job()
    action, lease, now = described_binding(job)
    match_action_lease(job, action, lease, now)
    with pytest.raises(ValueError):
        match_action_lease(
            job, action.model_copy(update={"parameters": {"job": {"forged": True}}}), lease, now
        )
    with pytest.raises(ValueError):
        match_action_lease(job, action, lease.model_copy(update={"run_id": uuid4()}), now)
    with pytest.raises(ValueError):
        match_action_lease(job, action, lease, lease.expires_at)
    with pytest.raises(ValueError):
        match_action_lease(
            job, action.model_copy(update={"resource": "foreign.repository"}), lease, now
        )
    with pytest.raises(ValueError):
        require_preparation(
            job,
            described_policy().model_copy(update={"company_id": uuid4()}),
            synthetic_capabilities(),
        )


def test_strict_limits_and_paths_do_not_promote_a_job_or_unknown_command() -> None:
    with pytest.raises(ValidationError):
        BuilderLimits(memory_bytes=4_294_967_297)
    with pytest.raises(ValidationError):
        BuilderLimits(cpu_millis=True)
    raw = described_job().model_dump(mode="json")
    raw["network"] = "host"
    with pytest.raises(ValidationError):
        BuilderJobSpec.model_validate(raw)
    with pytest.raises(ValueError):
        require_preparation(
            described_job().model_copy(update={"write_paths": ("apps/web/secrets",)}),
            described_policy(),
            synthetic_capabilities(),
        )
    with pytest.raises(ValidationError):
        BuilderCommandReceipt(
            command_key="unit",
            phase="post",
            outcome="outcome_unknown",
            exit_code=0,
            elapsed_millis=1,
        )
    with pytest.raises(ValidationError):
        BuilderCommandReceipt.model_validate(
            {
                "command_key": "unit",
                "phase": "post",
                "outcome": "exited",
                "exit_code": 0,
                "elapsed_millis": 1,
                "verdict": "pass",
            }
        )


@pytest.mark.parametrize(
    "image",
    ["dir:/private@sha256:" + "1" * 64, "registry.example/native:latest@sha256:" + "1" * 64],
)
def test_image_transport_and_mutable_tag_not_admitted(image: str) -> None:
    raw = described_policy().model_dump(mode="json")
    raw["image"] = image
    with pytest.raises(ValidationError):
        BuilderToolPolicy.model_validate(raw)
