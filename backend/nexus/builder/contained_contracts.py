"""Strict historical descriptions for containment; none grants execution authority."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID, uuid5

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from nexus.builder.contracts import BuilderValue, Digest
from nexus.builder.issued_parent_identity import (
    IssuedParentProviderVersion,
    current_issued_parent_profile,
    issued_parent_profile,
)
from nexus.builder.user_parent_identity import (
    USER_PARENT_METHOD_SHA256,
    USER_PARENT_PROVIDER_VERSION,
    UserParentProviderVersion,
    UserSystemdVersion,
    current_root_parent_profile,
    root_parent_profile,
)

UInt = Annotated[int, Field(ge=0, lt=2**64 - 1, strict=True)]
Positive = Annotated[int, Field(gt=0, lt=2**64 - 1, strict=True)]
ScopeUnit = Annotated[str, StringConstraints(pattern=r"^nexus-[a-z0-9-]{1,90}\.scope$")]


class ContainedValue(BuilderValue):
    """No coercion, unknown fields or mutable descriptions at this internal boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class UserManagerObservation(ContainedValue):
    """Actual daemon context from the private fixed user bus; descriptive, not authority."""

    manager: Literal["user"]
    version: UserSystemdVersion
    uid: int = Field(gt=0, lt=2**32, strict=True)
    query_route: Literal["fixed_local_user_bus"]


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

    user_manager: UserManagerObservation
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

    user_manager: UserManagerObservation
    uid: Positive
    boot_id: UUID
    self_cgroup_path: str
    mount_id: Positive
    mount_device: Positive
    mount_inode: Positive
    cgroup_path: str
    cgroup_inode: Positive
    directory_uid: UInt
    delegation_marker: Literal["present_1", "absent_user_manager"]
    controllers: frozenset[str]
    memory_bytes: Positive
    cpu_quota_us: Positive
    cpu_period_us: Positive
    pids: Positive


class HostPlacementIdentity(ContainedValue):
    """Stable observed post-seal facts; a portable description is never an ownership context."""

    company_id: UUID
    action_id: UUID
    task_id: UUID
    trace_id: UUID
    run_id: UUID
    original_intent_fence: Positive
    spec_sha256: Digest
    proposal_sha256: Digest
    execution_method_sha256: Digest
    container_id: Digest
    container_name: str
    image_id: Digest
    boot_id: UUID
    uid: Positive
    collector_pid: Positive
    collector_start_ticks: Positive
    runtime_pid: Positive
    runtime_start_ticks: Positive
    mount_id: Positive
    mount_device: Positive
    mount_inode: Positive
    scope_path: str
    scope_inode: Positive
    scope_uid: Positive
    runtime_path: str
    runtime_mount_id: Positive
    runtime_device: Positive
    runtime_inode: Positive
    runtime_uid: Positive

    @model_validator(mode="after")
    def exact_leaf(self) -> Self:
        if (
            cgroup_components(self.runtime_path) != (*cgroup_components(self.scope_path), "runtime")
            or self.runtime_mount_id != self.mount_id
            or self.runtime_device != self.mount_device
            or self.scope_uid != self.uid
            or self.runtime_uid != self.uid
            or self.collector_pid == self.runtime_pid
            or self.scope_inode == self.runtime_inode
            or self.container_name
            != "nexus-builder-" + uuid5(self.company_id, str(self.action_id)).hex
        ):
            raise ValueError("Issued host description differs from exact owned runtime leaf")
        return self


class ParentObservation(ContainedValue):
    """Historical scope evidence; future effect gates must obtain another fresh observation."""

    schema_version: Literal[
        "nexus.builder.parent-observation.v2", "nexus.builder.parent-observation.v3"
    ] = "nexus.builder.parent-observation.v2"
    provider_version: UserParentProviderVersion | IssuedParentProviderVersion = (
        USER_PARENT_PROVIDER_VERSION
    )
    provider_method_sha256: Digest = USER_PARENT_METHOD_SHA256
    expectation: ScopeExpectation
    unit: SystemdScopeFacts
    kernel: KernelScopeFacts
    observed_start_us: UInt
    observed_end_us: UInt
    deadline_us: Positive
    remaining_us: Positive
    issued_identity: HostPlacementIdentity | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    # One conditional provider-tuple comparison keeps legacy and issued identity bindings visible.
    @model_validator(mode="after")
    def fixed_provider_method(self) -> Self:
        """This pin describes the provider only, never the unissued full runtime method."""
        require_user_manager(self.unit.user_manager, self.expectation.uid)
        require_user_manager(self.kernel.user_manager, self.kernel.uid)
        if self.unit.user_manager != self.kernel.user_manager:
            raise ValueError("Unit and kernel user manager observations differ")
        manager = self.unit.user_manager.version
        pair = self.provider_version, self.provider_method_sha256
        if self.schema_version == "nexus.builder.parent-observation.v2":
            if (
                pair not in (root_parent_profile(manager), current_root_parent_profile(manager))
                or self.issued_identity is not None
            ):
                raise ValueError("User-parent provider method differs")
        elif (
            self.schema_version != "nexus.builder.parent-observation.v3"
            or pair not in (issued_parent_profile(manager), current_issued_parent_profile(manager))
            or self.issued_identity is None
        ):
            raise ValueError("Issued-parent provider identity is incomplete")
        else:
            owned = HostPlacementIdentity.model_validate(self.issued_identity.model_dump())
            expected, kernel = self.expectation, self.kernel
            if (
                owned.company_id,
                owned.action_id,
                owned.task_id,
                owned.trace_id,
                owned.run_id,
                owned.boot_id,
                owned.uid,
                owned.mount_id,
                owned.mount_device,
                owned.mount_inode,
                owned.scope_path,
                owned.scope_inode,
                owned.scope_uid,
                owned.runtime_path,
            ) != (
                expected.company_id,
                expected.action_id,
                expected.task_id,
                expected.trace_id,
                expected.run_id,
                kernel.boot_id,
                kernel.uid,
                kernel.mount_id,
                kernel.mount_device,
                kernel.mount_inode,
                kernel.cgroup_path,
                kernel.cgroup_inode,
                kernel.directory_uid,
                kernel.self_cgroup_path,
            ):
                raise ValueError("Issued-parent observed placement differs from actual scope facts")
        return self


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


def require_user_manager(manager: UserManagerObservation, uid: int) -> None:
    """Reject unknown/copied contexts before qualified ENODATA can be described."""
    if (
        type(manager) is not UserManagerObservation
        or manager.manager != "user"
        or type(manager.version) is not str
        or type(manager.uid) is not int
        or type(uid) is not int
        or manager.query_route != "fixed_local_user_bus"
        or manager.uid != uid
        or not 0 < uid < 2**32
    ):
        raise ValueError("Current supported user manager identity differs")
    root_parent_profile(manager.version)
