"""Strict host observation descriptions; byte/identity conformance is not execution authority."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from nexus.builder.contained_contracts import (
    ContainedEvidenceIdentity,
    ContainedValue,
    ParentObservation,
    Positive,
    UInt,
    cgroup_components,
)
from nexus.builder.contracts import Digest

OwnedName = Annotated[str, StringConstraints(pattern=r"^nexus-builder-[0-9a-f]{32}$")]
ObservationStatus = Literal["observed_contained", "unproven", "mismatch", "interrupted"]
ProcessRole = Literal["runtime", "conmon", "payload", "descendant"]
Diagnostic = Literal[
    "process_missing",
    "process_race",
    "identity_mismatch",
    "tree_incomplete",
    "overflow",
    "deadline",
    "io_unavailable",
    "parent_changed",
    "cancelled",
    "no_samples",
]


class ExactContainer(ContainedValue):
    """Server-selected issued object; action/image/name/full ID must bind actual inspection."""

    company_id: UUID
    action_id: UUID
    image_id: Digest
    container_id: Digest
    container_name: OwnedName
    memory_bytes: Positive
    cpu_quota_us: Positive
    cpu_period_us: Positive
    pids: Positive
    runtime_pid: Positive | None = None


class ProcessIdentity(ContainedValue):
    """Host PID plus start/boot and exact owned cgroup directory, never a mutable PID alone."""

    boot_id: UUID
    pid: Positive
    start_ticks: Positive
    role: ProcessRole
    cgroup_path: str
    mount_id: Positive
    cgroup_device: Positive
    cgroup_inode: Positive

    @field_validator("cgroup_path")
    @classmethod
    def exact_path(cls, value: str) -> str:
        cgroup_components(value)
        return value


class ObservationDeadline(ContainedValue):
    """One absolute monotonic end shared across sampling, inspection and later owned cleanup."""

    end_us: Positive

    @classmethod
    def from_budget(
        cls,
        parent: ParentObservation,
        now_us: int,
        budget_us: int,
        job_end_us: int,
    ) -> ObservationDeadline:
        """Seal one bounded end; later samples/inspection/cleanup cannot replenish it."""
        if (
            type(now_us) is not int
            or type(budget_us) is not int
            or type(job_end_us) is not int
            or not 0 < budget_us <= 1_200_000_000
            or now_us < 0
        ):
            raise ValueError("Observation total budget is not an exact finite bound")
        end = min(parent.deadline_us, now_us + budget_us, job_end_us)
        if end <= now_us:
            raise ValueError("Observation bounded operation has no remaining time")
        return cls(end_us=end)

    def remaining_us(self, now_us: int, parent: ParentObservation) -> int:
        """A later parent sample can reduce remaining time, never reset the original end."""
        return max(0, min(self.end_us, parent.deadline_us) - now_us)


class ObservedSample(ContainedValue):
    """Complete actual sample or an explicit retained uncertainty/mismatch."""

    parent: ParentObservation
    container: ExactContainer
    started_us: UInt
    finished_us: UInt
    deadline_end_us: Positive
    processes: tuple[ProcessIdentity, ...] = Field(default=(), max_length=256)
    retired_processes: tuple[ProcessIdentity, ...] = Field(default=(), max_length=256)
    status: ObservationStatus
    diagnostics: tuple[Diagnostic, ...] = Field(default=(), max_length=16)
    subtree_count: int = Field(default=0, ge=0, le=512, strict=True)
    tree_complete: bool = Field(default=False, strict=True)
    memory_bytes: Positive | None = None
    cpu_quota_us: Positive | None = None
    cpu_period_us: Positive | None = None
    pids: Positive | None = None

    @model_validator(mode="after")
    def complete_claim(self) -> Self:
        if self.started_us > self.finished_us:
            raise ValueError("Observation sample clock regressed")
        require_ancestry(self.parent, (*self.processes, *self.retired_processes))
        retired = {process_key(row) for row in self.retired_processes}
        if len(retired) != len(self.retired_processes) or retired & {
            process_key(row) for row in self.processes
        }:
            raise ValueError("Current and retired identities overlap or repeat")
        if self.status == "observed_contained":
            require_processes(self.parent, self.container, self.processes, self.finished_us)
            if (
                self.diagnostics
                or not self.tree_complete
                or self.subtree_count == 0
                or self.finished_us >= self.deadline_end_us
                or (self.memory_bytes, self.cpu_quota_us, self.cpu_period_us, self.pids)
                != (
                    self.container.memory_bytes,
                    self.container.cpu_quota_us,
                    self.container.cpu_period_us,
                    self.container.pids,
                )
            ):
                raise ValueError("Complete sample needs exact actual caps and no diagnostics")
        return self


class ContainedObservation(ContainedValue):
    """Immutable sidecar binds original issuance/result and actual host identities."""

    schema_version: Literal["nexus.builder.contained-observation.v1"] = (
        "nexus.builder.contained-observation.v1"
    )
    identity: ContainedEvidenceIdentity
    spec_sha256: Digest
    proposal_sha256: Digest
    selector_sha256: Digest
    provider_method_sha256: Digest
    container: ExactContainer
    parent: ParentObservation
    processes: tuple[ProcessIdentity, ...] = Field(default=(), max_length=256)
    retired_processes: tuple[ProcessIdentity, ...] = Field(default=(), max_length=256)
    last_sample: ObservedSample
    sample_count: int = Field(ge=1, le=12001, strict=True)
    sample_chain_sha256: Digest
    first_sample_us: UInt
    final_sample_us: UInt
    status: ObservationStatus
    diagnostics: tuple[Diagnostic, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def bound_original_identity(self) -> Self:
        ObservedSample.model_validate(self.last_sample.model_dump())
        if (self.identity.company_id, self.identity.action_id) != (
            self.container.company_id,
            self.container.action_id,
        ) or self.provider_method_sha256 != self.parent.provider_method_sha256:
            raise ValueError("Sidecar identity or provider method differs")
        require_ancestry(self.parent, (*self.processes, *self.retired_processes))
        if (
            self.last_sample.parent != self.parent
            or self.last_sample.container != self.container
            or self.final_sample_us != self.last_sample.finished_us
            or self.first_sample_us > self.last_sample.started_us
        ):
            raise ValueError("Sidecar final actual sample binding differs")
        if self.status == "observed_contained":
            current = {process_key(row) for row in self.last_sample.processes}
            retired = {process_key(row) for row in self.retired_processes}
            captured = {process_key(row) for row in self.processes}
            if (
                self.last_sample.status != "observed_contained"
                or self.diagnostics
                or len(captured) != len(self.processes)
                or current & retired
                or current | retired != captured
            ):
                raise ValueError("Contained observation cannot discard uncertainty")
        return self


class ContainmentRef(ContainedValue):
    """Descriptor only; store must read actual complete bytes before accepting this reference."""

    schema_version: Literal["nexus.builder.containment-ref.v1"] = "nexus.builder.containment-ref.v1"
    identity: ContainedEvidenceIdentity
    sha256: Digest
    byte_length: int = Field(gt=0, le=65536, strict=True)


def require_processes(
    parent: ParentObservation,
    container: ExactContainer,
    processes: tuple[ProcessIdentity, ...],
    final_us: int,
) -> None:
    """Role completeness and actual ancestry cannot be inferred from shortened inventories."""
    if (container.company_id, container.action_id) != (
        parent.expectation.company_id,
        parent.expectation.action_id,
    ) or not parent.observed_end_us <= final_us < parent.deadline_us:
        raise ValueError("Observed object/clock does not bind the actual parent")
    keys = {(row.boot_id, row.pid, row.start_ticks) for row in processes}
    if len(keys) != len(processes) or any(
        sum(row.role == role for row in processes) != 1 for role in ("payload", "conmon")
    ):
        raise ValueError("Actual payload/conmon identities missing or ambiguous")
    require_ancestry(parent, processes)
    if container.runtime_pid is not None and (
        sum(row.role == "runtime" and row.pid == container.runtime_pid for row in processes) != 1
    ):
        raise ValueError("Actual issued runtime PID identity is missing")


def require_ancestry(parent: ParentObservation, processes: tuple[ProcessIdentity, ...]) -> None:
    """Every current or historical record preserves its original observed ancestry."""
    root = cgroup_components(parent.kernel.cgroup_path)
    for row in processes:
        path = cgroup_components(row.cgroup_path)
        if (
            row.boot_id != parent.kernel.boot_id
            or row.mount_id != parent.kernel.mount_id
            or row.cgroup_device != parent.kernel.mount_device
            or path[: len(root)] != root
            or (path == root and row.cgroup_inode != parent.kernel.cgroup_inode)
        ):
            raise ValueError("Observed process boot/mount/component ancestry differs")


def process_key(row: ProcessIdentity) -> tuple[UUID, int, int]:
    """Retain every captured original process/start identity independently of later retirement."""
    return row.boot_id, row.pid, row.start_ticks


def parent_identity(parent: ParentObservation) -> dict[str, object]:
    """Fresh observed times may advance; original unit/boot/invocation/limits/inodes cannot."""
    return parent.model_dump(exclude={"observed_start_us", "observed_end_us", "remaining_us"})
