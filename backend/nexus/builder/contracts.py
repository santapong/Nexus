"""Strict immutable builder descriptions; decoding them grants no execution authority."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from nexus.builder.paths import relative_path
from nexus.company.contracts.base import Contract

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
GitObject = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Symbol = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]{0,99}$")]
Architecture = Literal["arm64", "amd64"]


class BuilderValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class RepositoryPin(BuilderValue):
    repository_symbol: Symbol
    commit: GitObject
    tree: GitObject
    archive_sha256: Digest


class BuilderLimits(BuilderValue):
    cpu_millis: int = Field(default=2000, ge=100, le=2000, strict=True)
    memory_bytes: int = Field(default=4_294_967_296, ge=67_108_864, le=4_294_967_296, strict=True)
    workspace_bytes: int = Field(default=2_147_483_648, ge=1_048_576, le=2_147_483_648, strict=True)
    output_bytes: int = Field(default=67_108_864, ge=1, le=67_108_864, strict=True)
    log_bytes: int = Field(default=1_048_576, ge=1, le=1_048_576, strict=True)
    command_seconds: int = Field(default=300, ge=1, le=300, strict=True)
    job_seconds: int = Field(default=1200, ge=1, le=1200, strict=True)
    pids: int = Field(default=256, ge=8, le=256, strict=True)

    @model_validator(mode="after")
    def total_bounds(self) -> Self:
        if self.output_bytes > self.workspace_bytes or self.command_seconds > self.job_seconds:
            raise ValueError("Builder child bounds exceed the job envelope")
        return self


class CommandRef(BuilderValue):
    command_key: Symbol
    phase: Literal["baseline", "post"]


class BuilderJobSpec(Contract):
    builder_version: Literal["nexus.builder.v1"] = "nexus.builder.v1"
    task_id: UUID
    trace_id: UUID
    run_id: UUID
    workspace_id: UUID
    actor_id: UUID
    action_id: UUID
    policy_symbol: Symbol
    resource_symbol: Symbol
    architecture: Architecture
    source: RepositoryPin
    patch_sha256: Digest | None = None
    write_paths: tuple[str, ...] = Field(min_length=1, max_length=16)
    artifact_paths: tuple[str, ...] = Field(min_length=1, max_length=16)
    commands: tuple[CommandRef, ...] = Field(min_length=2, max_length=8)
    limits: BuilderLimits
    network: Literal["none"] = "none"

    @field_validator("write_paths", "artifact_paths")
    @classmethod
    def safe_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("Builder paths must be distinct")
        for value in values:
            relative_path(value)
        return values

    @model_validator(mode="after")
    def ordered_phases(self) -> Self:
        phases = tuple(row.phase for row in self.commands)
        if "baseline" not in phases or "post" not in phases or phases != tuple(sorted(phases)):
            raise ValueError("Baseline commands must precede post-change commands")
        pairs = tuple((row.phase, row.command_key) for row in self.commands)
        if len(set(pairs)) != len(pairs):
            raise ValueError("Builder commands cannot repeat within a phase")
        return self


class BuilderCapabilities(BuilderValue):
    """Trusted qualification facts, not a public input or self-reported permission."""

    architecture: Architecture
    rootless: bool = Field(strict=True)
    cgroup_v2: bool = Field(strict=True)
    controllers: frozenset[Literal["cpu", "memory", "pids", "io", "cpuset"]]
    hard_workspace_quota: bool = Field(strict=True)
    network_none_verified: bool = Field(strict=True)
    image_present: bool = Field(strict=True)
    qualified_image: str


class BuilderArtifact(BuilderValue):
    path: str
    sha256: Digest
    byte_length: int = Field(ge=0, strict=True)

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        relative_path(value)
        return value


class BuilderCommandReceipt(BuilderValue):
    command_key: Symbol
    phase: Literal["baseline", "post"]
    exit_code: int | None = Field(default=None, strict=True)
    outcome: Literal[
        "exited", "timed_out", "cancelled", "resource_limited", "tool_missing", "outcome_unknown"
    ]
    stdout_sha256: Digest | None = None
    stderr_sha256: Digest | None = None
    log_truncated: bool = Field(default=False, strict=True)
    elapsed_millis: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def known_exit(self) -> Self:
        if self.outcome == "exited" and self.exit_code is None:
            raise ValueError("An exited command needs its actual exit code")
        if self.outcome in {"tool_missing", "outcome_unknown"} and self.exit_code is not None:
            raise ValueError("An unobserved command cannot claim an exit code")
        return self
