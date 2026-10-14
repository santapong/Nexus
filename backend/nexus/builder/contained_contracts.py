"""Strict historical descriptions for containment; none grants execution authority."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from nexus.builder.contracts import BuilderValue, Digest

UInt = Annotated[int, Field(ge=0, lt=2**64 - 1, strict=True)]
Positive = Annotated[int, Field(gt=0, lt=2**64 - 1, strict=True)]
ScopeUnit = Annotated[str, StringConstraints(pattern=r"^nexus-[a-z0-9-]{1,90}\.scope$")]


class ContainedValue(BuilderValue):
    """No coercion, unknown fields or mutable descriptions at this internal boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class ScopeExpectation(ContainedValue):
    """Process-local trusted launcher expectations; decoding is not a permission."""

    task_id: UUID
    trace_id: UUID
    company_id: UUID
    action_id: UUID
    run_id: UUID
    uid: Positive
    boot_id: UUID
    unit: ScopeUnit
    invocation_id: UUID
    launcher_nonce: UUID
    mount_id: Positive
    mount_device: Positive
    mount_inode: Positive
    cgroup_path: str
    cgroup_inode: Positive
    memory_bytes: Positive
    cpu_quota_us: Positive
    cpu_period_us: Positive
    pids: Positive
    runtime_us: Positive
    stop_us: Positive
    minimum_remaining_us: Positive

    @field_validator("cgroup_path")
    @classmethod
    def exact_path(cls, value: str) -> str:
        """Canonical absolute component paths only, without normalization."""
        cgroup_components(value)
        return value

    @model_validator(mode="after")
    def finite_envelope(self) -> Self:
        if not self.cgroup_path.endswith("/" + self.unit):
            raise ValueError("Expected scope path differs from the exact unit")
        if self.minimum_remaining_us > self.runtime_us or self.stop_us > 3_000_000:
            raise ValueError("Expected scope timing exceeds the fixed envelope")
        if (
            self.runtime_us > 1_200_000_000
            or self.memory_bytes > 4_294_967_296
            or self.pids > 256
            or self.cpu_quota_us > 2 * self.cpu_period_us
        ):
            raise ValueError("Expected scope exceeds the fixed builder maximum caps")
        if self.invocation_id.int == 0 or self.boot_id.int == 0 or self.launcher_nonce.int == 0:
            raise ValueError("Expected current scope identity must be nonempty")
        return self


class SystemdScopeFacts(ContainedValue):
    """Actual typed Unit/Scope replies, before independent kernel validation."""

    unit: str
    load_state: str
    active_state: str
    invocation_id: UUID
    active_enter_us: Positive
    cgroup_path: str
    runtime_us: Positive
    randomized_extra_us: UInt
    delegated: bool
    memory_bytes: Positive
    cpu_per_second_us: Positive
    cpu_period_us: Positive
    pids: Positive
    kill_mode: str
    send_sigkill: bool
    stop_us: Positive


class KernelScopeFacts(ContainedValue):
    """Actual owned descriptor, boot, self-membership and numeric kernel limits."""

    uid: Positive
    boot_id: UUID
    self_cgroup_path: str
    mount_id: Positive
    mount_device: Positive
    mount_inode: Positive
    cgroup_path: str
    cgroup_inode: Positive
    directory_uid: UInt
    delegation_marker: bool
    controllers: frozenset[str]
    memory_bytes: Positive
    cpu_quota_us: Positive
    cpu_period_us: Positive
    pids: Positive


class ParentObservation(ContainedValue):
    """Historical scope evidence; future effect gates must obtain another fresh observation."""

    schema_version: Literal["nexus.builder.parent-observation.v1"] = (
        "nexus.builder.parent-observation.v1"
    )
    expectation: ScopeExpectation
    unit: SystemdScopeFacts
    kernel: KernelScopeFacts
    observed_start_us: UInt
    observed_end_us: UInt
    deadline_us: Positive
    remaining_us: Positive


class ObservationBounds(ContainedValue):
    """Closed caps; future observer/inspection/cleanup also shares a total deadline."""

    total_io_us: Literal[3_000_000] = 3_000_000
    stdout_bytes: Literal[16_384] = 16_384
    stderr_bytes: Literal[4_096] = 4_096
    kernel_bytes: Literal[4_096] = 4_096
    process_count: Literal[256] = 256
    subtree_count: Literal[512] = 512
    sidecar_bytes: Literal[65_536] = 65_536

    @field_validator("*", mode="before")
    @classmethod
    def integer_pins(cls, value: object) -> object:
        """Literal equality cannot accept a float/bool in place of fixed integer caps."""
        if type(value) is not int:
            raise ValueError("Observation caps require exact integers")
        return value


class ContainedEvidenceIdentity(ContainedValue):
    """Write-once identity uses original issuance, never a replacement replay lease fence."""

    company_id: UUID
    action_id: UUID
    original_intent_fence: Positive
    result_base_sha256: Digest
    execution_method_sha256: Digest


def cgroup_components(value: str) -> tuple[str, ...]:
    """Reject aliases before opening any component beneath the fixed cgroup mount."""
    parts = tuple(value.split("/")[1:])
    if (
        not value.startswith("/")
        or not parts
        or len(value) > 1024
        or any(part in {"", ".", ".."} or any(ord(c) < 33 for c in part) for part in parts)
    ):
        raise ValueError("Scope cgroup path is not canonical")
    return parts
