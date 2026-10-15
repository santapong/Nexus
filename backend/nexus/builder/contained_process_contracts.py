"""Server-compiler process descriptions and synchronous final window checks; no effect authority."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise
from typing import TYPE_CHECKING, Annotated, Literal, Self
from uuid import UUID, uuid5

from pydantic import Field, StringConstraints, model_validator

from nexus.builder.contained_contracts import (
    ContainedValue,
    HostPlacementIdentity,
    ParentObservation,
    Positive,
    cgroup_components,
)
from nexus.builder.contained_diagnostics import (
    DiscoveryRecorder,
    ErrorKind,
    Phase,
    ProcessDiagnostic,
)
from nexus.builder.contained_evidence_types import (
    ExactContainer,
    ObservationDeadline,
    ObservedSample,
)
from nexus.builder.contained_parent_diagnostics import ParentAttempt
from nexus.builder.contained_process_diagnostics import (
    process_diagnostic as process_diagnostic,
)
from nexus.builder.contained_process_diagnostics import (
    sample_trace as sample_trace,
)
from nexus.builder.contained_scope import require_current_parent_profile
from nexus.builder.contained_spawn_window import SpawnWindow
from nexus.builder.contracts import Digest
from nexus.builder.process import ProcessCapture

if TYPE_CHECKING:
    from nexus.builder.contained_issued_context import OwnedIssuedContext, OwnedStart

OwnedName = Annotated[str, StringConstraints(pattern=r"^nexus-builder-[0-9a-f]{32}$")]
RuntimeMembership = Literal["observed_path", "foreign_path", "unavailable"]


class ProcessRunBinding(ContainedValue):
    """Original actual issued fence is independent of any subsequent current lease."""

    company_id: UUID
    action_id: UUID
    task_id: UUID
    trace_id: UUID
    run_id: UUID
    original_intent_fence: Positive
    image_id: Digest
    spec_sha256: Digest
    proposal_sha256: Digest
    execution_method_sha256: Digest
    container_name: OwnedName

    @model_validator(mode="after")
    def native_name(self) -> Self:
        if (
            self.container_name
            != "nexus-builder-" + uuid5(self.company_id, str(self.action_id)).hex
        ):
            raise ValueError("Contained object name differs from exact native issuance")
        return self


class PreparedContainedLaunch(ContainedValue):
    """Root compiler constructs this exact descriptor; possessing it grants no call permit."""

    binding: ProcessRunBinding
    argv: tuple[str, ...] = Field(min_length=10, max_length=256)
    argv_sha256: Digest
    memory_bytes: Positive
    cpu_quota_us: Positive
    cpu_period_us: Positive
    pids: Positive

    @model_validator(mode="after")
    def exact_closed_selectors(self) -> Self:
        argv = self.argv
        if (
            argv[:4] != ("/usr/bin/podman", "--remote=false", "--cgroup-manager=cgroupfs", "run")
            or argv.count("--cgroups=split") != 1
            or any("\x00" in value or "\n" in value or "\r" in value for value in argv)
            or any(
                value.startswith(("--cgroup-parent", "--privileged", "--remote=true"))
                for value in argv
            )
        ):
            raise ValueError("Contained launch differs from fixed local cgroupfs/split boundary")
        _require_pair(argv, "--name", self.binding.container_name)
        for value in (
            f"nexus.builder.company={self.binding.company_id}",
            f"nexus.builder.action={self.binding.action_id}",
        ):
            _require_pair(argv, "--label", value)
        digest = hashlib.sha256(json.dumps(argv, separators=(",", ":")).encode()).hexdigest()
        if digest != self.argv_sha256:
            raise ValueError("Contained launch argv differs from the complete compiler descriptor")
        return self


class RuntimeCapture(ContainedValue):
    """Unconditional owned child witness; proc path alone does not qualify mount/containment."""

    pid: Positive
    start_ticks: Positive | None
    cgroup_path: str | None = Field(max_length=4096)
    parent_membership: RuntimeMembership
    reap: Literal["waited", "unresolved"]

    @model_validator(mode="after")
    def available_identity(self) -> Self:
        if self.parent_membership != "unavailable" and (
            self.start_ticks is None or self.cgroup_path is None
        ):
            raise ValueError("Contained runtime path witness lacks its actual PID start identity")
        return self


@dataclass(frozen=True)
class StartedContainedProcess:
    """Private live handle; no serialized process token can restart it."""

    process: asyncio.subprocess.Process
    parent: ParentObservation
    window: SpawnWindow
    runtime_start_ticks: int | None
    runtime_cgroup_path: str | None
    runtime_membership: RuntimeMembership
    owned_start: OwnedStart | None = None

    def runtime(self, wait: asyncio.Task[int]) -> RuntimeCapture:
        """A terminal wait is separate from any cached engine or descendant state."""
        return RuntimeCapture(
            pid=self.process.pid,
            start_ticks=self.runtime_start_ticks,
            cgroup_path=self.runtime_cgroup_path,
            parent_membership=self.runtime_membership,
            reap="waited"
            if wait.done() and not wait.cancelled() and wait.exception() is None
            else "unresolved",
        )


@dataclass
class ProcessSampling:
    """Per-invocation host memory; the first sealed ID survives failed observations."""

    out: asyncio.Task[bytes]
    err: asyncio.Task[bytes]
    wait: asyncio.Task[int]
    samples: list[ObservedSample] = field(default_factory=list)
    sealed: ExactContainer | None = None
    discovery: DiscoveryRecorder = field(default_factory=DiscoveryRecorder)
    phase: Phase = "initial"
    error_type: ErrorKind = "none"
    errno: int | None = None
    parent_attempt: ParentAttempt | None = None
    issued_context: OwnedIssuedContext | None = None
    issued_identity: HostPlacementIdentity | None = None
    issued_cleanup: Literal["closed", "deferred"] | None = None


class ContainedRunCapture(ContainedValue):
    """Raw output and host evidence; strict v2 decoding/publishing stays Root-owned."""

    capture: ProcessCapture
    runtime: RuntimeCapture
    parent: ParentObservation
    deadline: ObservationDeadline
    sealed_container: ExactContainer | None = None
    samples: tuple[ObservedSample, ...] = Field(default=(), max_length=12001)
    infrastructure: Literal["known", "unproven", "unresolved"]
    limitations: tuple[str, ...] = Field(default=(), max_length=16)
    diagnostic: ProcessDiagnostic | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    parent_attempt: ParentAttempt | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    issued_identity: HostPlacementIdentity | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    issued_cleanup: Literal["closed", "deferred"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def actual_samples(self) -> Self:
        if self.parent_attempt is not None and (
            self.parent_attempt.error_type == "none"
            or self.parent_attempt.expectation_sha256
            != hashlib.sha256(self.parent.expectation.model_dump_json().encode()).hexdigest()
        ):
            raise ValueError("Raw parent failure metadata differs from original expected scope")
        for sample in self.samples:
            row = ObservedSample.model_validate(sample.model_dump())
            if row.parent.issued_identity is not None:
                if (
                    row.parent.issued_identity != self.issued_identity
                    or self.parent.issued_identity is not None
                    or row.parent.expectation != self.parent.expectation
                    or row.parent.unit != self.parent.unit
                    or row.parent.deadline_us != self.parent.deadline_us
                    or row.parent.kernel.model_dump(exclude={"self_cgroup_path"})
                    != self.parent.kernel.model_dump(exclude={"self_cgroup_path"})
                ):
                    raise ValueError("Raw preissue anchor differs from post-seal sample identity")
            elif self.issued_identity is not None:
                raise ValueError(
                    "Issued raw capture cannot replace post-seal samples with legacy parent"
                )
            if (
                row.container != self.sealed_container
                or row.deadline_end_us != self.deadline.end_us
            ):
                raise ValueError("Contained raw sample binds another object or operation end")
            if row.status == "observed_contained" and not any(
                process.role == "runtime"
                and process.pid == self.runtime.pid
                and process.start_ticks == self.runtime.start_ticks
                for process in row.processes
            ):
                raise ValueError("Contained sample omits original observed runtime identity")
        if self.infrastructure == "known" and (
            not self.samples
            or self.sealed_container is None
            or self.limitations
            or self.runtime.parent_membership != "observed_path"
            or self.runtime.reap != "waited"
            or self.capture.interruption is not None
            or any(row.status != "observed_contained" for row in self.samples)
            or (self.issued_identity is not None and self.issued_cleanup != "closed")
        ):
            raise ValueError("Contained known infrastructure cannot discard uncertainty")
        return self


def require_spawn_ready(
    launch: PreparedContainedLaunch,
    binding: ProcessRunBinding,
    parent: ParentObservation,
    window: SpawnWindow,
    *,
    monotonic_now_us: int,
    utc_now: datetime,
) -> None:
    """The last synchronous check must be immediately followed by the exact spawn primitive."""
    prepared = PreparedContainedLaunch.model_validate(launch.model_dump())
    if (
        parent.schema_version != "nexus.builder.parent-observation.v2"
        or parent.issued_identity is not None
    ):
        raise ValueError("Preissue spawn requires strict original root observation")
    require_current_parent_profile(parent)
    expected = ProcessRunBinding.model_validate(binding.model_dump())
    if prepared.binding != expected or (
        parent.expectation.company_id,
        parent.expectation.action_id,
        parent.expectation.task_id,
        parent.expectation.trace_id,
        parent.expectation.run_id,
    ) != (
        expected.company_id,
        expected.action_id,
        expected.task_id,
        expected.trace_id,
        expected.run_id,
    ):
        raise ValueError("Contained parent or launch binds another exact issued operation")
    if not parent.observed_end_us <= monotonic_now_us < parent.deadline_us:
        raise ValueError("Contained parent current deadline/clock is unavailable")
    if (
        launch.memory_bytes > parent.kernel.memory_bytes
        or launch.pids > parent.kernel.pids
        or launch.cpu_quota_us * parent.kernel.cpu_period_us
        > parent.kernel.cpu_quota_us * launch.cpu_period_us
    ):
        raise ValueError("Contained child numeric bounds exceed the actual parent envelope")
    window.require_current(utc_now=utc_now, monotonic_now_us=monotonic_now_us)


def _require_pair(argv: tuple[str, ...], key: str, value: str) -> None:
    if sum(a == key and b == value for a, b in pairwise(argv)) != 1:
        raise ValueError("Contained launch identity pair is missing or duplicated")


def capture_limits(stdout_limit: int, stderr_limit: int) -> None:
    """Validate raw capture bounds before the single spawn."""
    if (
        type(stdout_limit) is not int
        or not 0 < stdout_limit <= 262_144_000
        or type(stderr_limit) is not int
        or not 0 < stderr_limit <= 1_048_576
    ):
        raise ValueError("Contained raw output bounds are unavailable")


def runtime_membership(path: str | None, parent: ParentObservation) -> RuntimeMembership:
    if path is None:
        return "unavailable"
    expected, actual = cgroup_components(parent.kernel.cgroup_path), cgroup_components(path)
    return "observed_path" if actual[: len(expected)] == expected else "foreign_path"
