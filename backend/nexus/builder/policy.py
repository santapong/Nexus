"""Server command/image configuration prepares descriptions and never issues an effect permit."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.builder.contracts import BuilderCapabilities, BuilderJobSpec, BuilderValue, Symbol
from nexus.builder.node_contracts import NodeRuntimeInputs, absent
from nexus.builder.paths import permitted_path, relative_path
from nexus.company.contracts.actions import ActionProposal
from nexus.execution.runtime_contracts import ExecutionLease


class BuilderCommandPolicy(BuilderValue):
    command_key: Symbol
    argv: tuple[str, ...] = Field(min_length=1, max_length=32)
    directory: str

    @model_validator(mode="after")
    def ordinary_command(self) -> Self:
        if any(not value or len(value) > 512 or "\x00" in value for value in self.argv):
            raise ValueError("Configured command arguments exceed their boundary")
        if self.directory != ".":
            relative_path(self.directory)
        return self


class BuilderToolPolicy(BuilderValue):
    company_id: UUID
    policy_symbol: Symbol
    resource_symbol: Symbol
    repository_symbol: Symbol
    image: str = Field(pattern=r"^[a-z0-9][a-z0-9./:_-]{2,200}@sha256:[0-9a-f]{64}$")
    commands: tuple[BuilderCommandPolicy, ...] = Field(min_length=1, max_length=8)
    write_paths: tuple[str, ...] = Field(min_length=1, max_length=16)
    artifact_paths: tuple[str, ...] = Field(min_length=1, max_length=16)
    runtime_inputs: NodeRuntimeInputs | None = Field(default=None, exclude_if=absent)

    @model_validator(mode="after")
    def exact_policy(self) -> Self:
        reference = self.image.split("@", 1)[0]
        if "/" not in reference:
            raise ValueError("Builder image needs a qualified registry and digest")
        registry, path = reference.split("/", 1)
        if (
            "." not in registry
            and registry != "localhost"
            and not registry.startswith("localhost:")
        ) or ":" in path:
            raise ValueError("Builder image transport or mutable tag is unsupported")
        if len({row.command_key for row in self.commands}) != len(self.commands):
            raise ValueError("Configured command keys must be distinct")
        for path in (*self.write_paths, *self.artifact_paths):
            relative_path(path)
        return self


def require_preparation(
    job: BuilderJobSpec, policy: BuilderToolPolicy, capabilities: BuilderCapabilities
) -> None:
    job = BuilderJobSpec.model_validate_json(job.model_dump_json())
    policy = BuilderToolPolicy.model_validate_json(policy.model_dump_json())
    capabilities = BuilderCapabilities.model_validate_json(capabilities.model_dump_json())
    if (job.company_id, job.policy_symbol, job.resource_symbol, job.source.repository_symbol) != (
        policy.company_id,
        policy.policy_symbol,
        policy.resource_symbol,
        policy.repository_symbol,
    ) or job.architecture != capabilities.architecture:
        raise ValueError("Builder policy or architecture does not match")
    if (
        not capabilities.rootless
        or not capabilities.cgroup_v2
        or not {"cpu", "memory", "pids"} <= capabilities.controllers
        or not capabilities.hard_workspace_quota
        or not capabilities.network_none_verified
        or not capabilities.image_present
        or capabilities.qualified_image != policy.image
    ):
        raise ValueError("Builder sandbox capabilities are not qualified")
    if not {row.command_key for row in job.commands} <= {
        row.command_key for row in policy.commands
    }:
        raise ValueError("Builder command is not configured")
    for selected, allowed in (
        (job.write_paths, policy.write_paths),
        (job.artifact_paths, policy.artifact_paths),
    ):
        if not all(permitted_path(value, allowed) for value in selected):
            raise ValueError("Builder paths exceed the configured scope")


def match_action_lease(
    job: BuilderJobSpec, action: ActionProposal, lease: ExecutionLease, now: datetime
) -> None:
    """Structural/current-time check only; actual M1/current DB authority is still mandatory."""
    expected = (job.company_id, job.task_id, job.trace_id, job.actor_id, job.action_id)
    if expected != (
        action.company_id,
        action.task_id,
        action.trace_id,
        action.actor_id,
        action.action_id,
    ):
        raise ValueError("Builder action scope differs")
    if (
        (job.company_id, job.task_id, job.trace_id, job.actor_id, job.workspace_id, job.run_id)
        != (
            lease.company_id,
            lease.task_id,
            lease.trace_id,
            lease.actor_id,
            lease.workspace_id,
            lease.run_id,
        )
        or lease.mode != "execute"
        or now.utcoffset() is None
        or lease.expires_at <= now
    ):
        raise ValueError("Builder lease scope or time differs")
    if (
        action.tool != "company.builder.run.v1"
        or action.tool_version != "v1"
        or action.resource != job.resource_symbol
        or action.parameters != {"job": job.model_dump(mode="json")}
    ):
        raise ValueError("Builder proposal does not bind the exact immutable job")


def prepare_podman_argv(
    job: BuilderJobSpec,
    policy: BuilderToolPolicy,
    capabilities: BuilderCapabilities,
    command_key: str,
    source: Path,
) -> tuple[str, ...]:
    """Return a fixed no-network command description; this function never calls Podman."""
    require_preparation(job, policy, capabilities)
    command = next((row for row in policy.commands if row.command_key == command_key), None)
    if command is None or command_key not in {row.command_key for row in job.commands}:
        raise ValueError("Builder command is unavailable")
    if (
        not source.is_absolute()
        or source.resolve(strict=True) != source
        or not source.is_dir()
        or any(char in str(source) for char in ":,\n\r\x00")
    ):
        raise ValueError("Prepared source directory is unavailable")
    directory = "/workspace" if command.directory == "." else f"/workspace/{command.directory}"
    limit = job.limits
    return (
        "podman",
        "--remote=false",
        "run",
        "--pull=never",
        "--network=none",
        "--http-proxy=false",
        "--read-only",
        "--read-only-tmpfs=false",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        f"--cpus={limit.cpu_millis / 1000:g}",
        f"--memory={limit.memory_bytes}",
        f"--memory-swap={limit.memory_bytes}",
        f"--pids-limit={limit.pids}",
        "--volume",
        f"{source}:/workspace:ro",
        "--workdir",
        directory,
        "--env=CI=1",
        "--env=NEXT_TELEMETRY_DISABLED=1",
        "--env=HOME=/tmp/home",
        policy.image,
        *command.argv,
    )
