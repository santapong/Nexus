"""Bounded private host diagnostics grant no containment, publication or cleanup authority."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Literal, Self, cast
from uuid import UUID

from pydantic import Field, model_validator

from nexus.builder.contained_contracts import ContainedValue, Positive, UInt
from nexus.builder.contained_evidence_store import (
    _directory,
    _exists,
    _publish,
    _read_file,
    _unique_pairs,
)
from nexus.builder.contained_evidence_types import Diagnostic, ExactContainer, ObservationStatus
from nexus.builder.contracts import Digest

ErrorKind = Literal[
    "none",
    "DiscoveryUnavailableError",
    "ValueError",
    "ValidationError",
    "OSError",
    "TimeoutError",
    "CancelledError",
    "other",
]
Phase = Literal["initial", "watch", "discovery", "parent", "sample", "wait", "capture", "complete"]


class DiagnosticIdentity(ContainedValue):
    company_id: UUID
    action_id: UUID
    task_id: UUID
    trace_id: UUID
    run_id: UUID
    original_intent_fence: Positive
    spec_sha256: Digest
    proposal_sha256: Digest
    execution_method_sha256: Digest


class OutputDigest(ContainedValue):
    """Length/SHA of observed bytes only; never asserts an uncaptured full output stream."""

    observed_bytes: UInt
    observed_sha256: Digest


class StreamObservation(OutputDigest):
    """Prefixes are only from the fixed local inspect command, not sandbox command output."""

    prefix_base64: str = Field(max_length=5464)
    complete: bool
    overflow: bool
    byte_limit: int = Field(ge=1, le=65536, strict=True)

    @model_validator(mode="after")
    def bounded_observed_prefix(self) -> Self:
        raw = base64.b64decode(self.prefix_base64, validate=True)
        if (
            len(raw) > 4096
            or len(raw) > self.observed_bytes
            or self.observed_bytes > self.byte_limit + 1
        ):
            raise ValueError("Fixed-inspect diagnostic prefix/count exceeds bounds")
        if self.overflow and self.complete:
            raise ValueError("Overflow cannot claim a complete stream")
        return self


class InspectAttempt(ContainedValue):
    kind: Literal["fixed_local_inspect"] = "fixed_local_inspect"
    index: Positive
    started_us: UInt
    finished_us: UInt
    argv_sha256: Digest
    child_pid: Positive | None
    exit_code: int | None
    reaped: bool
    stdout: StreamObservation
    stderr: StreamObservation
    error_type: ErrorKind
    errno: int | None = Field(default=None, ge=0, le=4095, strict=True)

    @model_validator(mode="after")
    def ordered_clock(self) -> Self:
        if self.finished_us < self.started_us:
            raise ValueError("Inspect diagnostic clock regressed")
        return self


class DiscoveryTrace(ContainedValue):
    total: UInt
    first: InspectAttempt | None
    last: InspectAttempt | None
    omitted: UInt

    @model_validator(mode="after")
    def exact_count(self) -> Self:
        if self.total == 0:
            if self.first is not None or self.last is not None or self.omitted:
                raise ValueError("Empty trace cannot invent attempts")
        elif (
            self.first is None
            or self.last is None
            or self.first.index != 1
            or self.last.index != self.total
            or self.omitted != max(0, self.total - 2)
        ):
            raise ValueError("Inspect trace must retain complete count and exact first/last")
        return self


class Count(ContainedValue):
    key: ObservationStatus | Diagnostic
    count: Positive


class SampleSummary(ContainedValue):
    started_us: UInt
    finished_us: UInt
    status: ObservationStatus
    diagnostics: tuple[Diagnostic, ...] = Field(max_length=16)
    sample_sha256: Digest
    process_count: int = Field(ge=0, le=256, strict=True)
    retired_count: int = Field(ge=0, le=256, strict=True)
    tree_complete: bool
    subtree_count: int = Field(ge=0, le=512, strict=True)
    memory_bytes: Positive | None
    cpu_quota_us: Positive | None
    cpu_period_us: Positive | None
    pids: Positive | None


class SampleTrace(ContainedValue):
    total: int = Field(ge=0, le=12001, strict=True)
    status_counts: tuple[Count, ...] = Field(max_length=4)
    diagnostic_counts: tuple[Count, ...] = Field(max_length=16)
    chain_sha256: Digest
    first: SampleSummary | None
    last: SampleSummary | None
    omitted: UInt

    @model_validator(mode="after")
    def summarized_complete_count(self) -> Self:
        if sum(row.count for row in self.status_counts) != self.total or self.omitted != max(
            0, self.total - 2
        ):
            raise ValueError("Sample summary counts are incomplete")
        if self.total == 0 and (self.first is not None or self.last is not None):
            raise ValueError("Empty sample trace cannot invent endpoints")
        if self.total > 0 and (self.first is None or self.last is None):
            raise ValueError("Sample trace requires both actual endpoints")
        if any(
            row.key not in {"observed_contained", "unproven", "mismatch", "interrupted"}
            for row in self.status_counts
        ):
            raise ValueError("Sample status counts contain another diagnostic key")
        for counts in (self.status_counts, self.diagnostic_counts):
            if len({row.key for row in counts}) != len(counts):
                raise ValueError("Diagnostic counts repeat a key")
        return self


class RuntimeDiagnostic(ContainedValue):
    pid: Positive
    start_ticks: Positive | None
    cgroup_path: str | None = Field(max_length=4096)
    parent_membership: Literal["observed_path", "foreign_path", "unavailable"]
    reap: Literal["waited", "unresolved"]


class ProcessDiagnostic(ContainedValue):
    schema_version: Literal["nexus.builder.process-diagnostic.v1"] = (
        "nexus.builder.process-diagnostic.v1"
    )
    phase_kind: Literal["raw"] = "raw"
    identity: DiagnosticIdentity
    parent_sha256: Digest
    deadline_end_us: Positive
    infrastructure: Literal["known", "unproven", "unresolved"]
    runtime: RuntimeDiagnostic
    sealed_container: ExactContainer | None
    stdout: OutputDigest
    stderr: OutputDigest
    exit_code: int | None
    interruption: ErrorKind | Literal["capture_or_reap_unresolved"] | None
    phase: Phase
    error_type: ErrorKind
    errno: int | None = Field(default=None, ge=0, le=4095, strict=True)
    discovery: DiscoveryTrace
    samples: SampleTrace


class FinalizationDiagnostic(ContainedValue):
    schema_version: Literal["nexus.builder.finalization-diagnostic.v1"] = (
        "nexus.builder.finalization-diagnostic.v1"
    )
    phase_kind: Literal["final"] = "final"
    identity: DiagnosticIdentity
    status: ObservationStatus
    diagnostics: tuple[Diagnostic, ...] = Field(max_length=16)
    sample_count: int = Field(ge=0, le=12001, strict=True)
    sample_chain_sha256: Digest
    error_type: ErrorKind = "none"
    errno: int | None = Field(default=None, ge=0, le=4095, strict=True)


class DiagnosticRef(ContainedValue):
    schema_version: Literal["nexus.builder.diagnostic-ref.v1"] = "nexus.builder.diagnostic-ref.v1"
    identity: DiagnosticIdentity
    phase: Literal["raw", "final"]
    sha256: Digest
    byte_length: int = Field(gt=0, le=65536, strict=True)


class DiscoveryRecorder:
    """Trusted per-run in-memory count and first/last observations; no user callback or permit."""

    def __init__(self) -> None:
        self.total = 0
        self.first: InspectAttempt | None = None
        self.last: InspectAttempt | None = None

    def record(self, attempt: InspectAttempt) -> None:
        value = InspectAttempt.model_validate(attempt.model_dump())
        if value.index != self.total + 1:
            raise ValueError("Discovery recorder index is not consecutive")
        self.total += 1
        self.first = self.first or value
        self.last = value

    def snapshot(self) -> DiscoveryTrace:
        return DiscoveryTrace(
            total=self.total, first=self.first, last=self.last, omitted=max(0, self.total - 2)
        )


class ContainmentDiagnosticStore:
    """Original-fence diagnostic phases reuse private IO; they never issue success refs."""

    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise ValueError("Diagnostic root must be absolute")
        root.mkdir(mode=0o700, parents=False, exist_ok=True)
        fd = _directory(root)
        original = os.fstat(fd)
        os.close(fd)
        self.root, self._root_identity = root, (original.st_dev, original.st_ino)

    @staticmethod
    def filename(identity: DiagnosticIdentity, phase: Literal["raw", "final"]) -> str:
        value = DiagnosticIdentity.model_validate(identity.model_dump())
        if phase not in ("raw", "final"):
            raise ValueError("Unknown diagnostic phase")
        digest = hashlib.sha256(value.model_dump_json().encode()).hexdigest()
        return f"diagnostic-{value.company_id.hex}-{value.action_id.hex}-{phase}-{digest}.json"

    async def save_once(self, record: ProcessDiagnostic | FinalizationDiagnostic) -> DiagnosticRef:
        value = _record(record.model_dump())
        raw = value.model_dump_json().encode()
        if len(raw) > 65536:
            raise ValueError("Diagnostic phase exceeds64KiB complete cap")
        ref = DiagnosticRef(
            identity=value.identity,
            phase=value.phase_kind,
            sha256=hashlib.sha256(raw).hexdigest(),
            byte_length=len(raw),
        )
        await asyncio.to_thread(self._save, raw, ref)
        return ref

    def _save(self, raw: bytes, reference: DiagnosticRef) -> None:
        fd = _directory(self.root, self._root_identity)
        name = self.filename(reference.identity, reference.phase)
        try:
            if _exists(fd, name + ".pending"):
                raise FileExistsError("Diagnostic pending phase requires explicit recovery")
            if _exists(fd, name):
                if _read_file(fd, name) != raw:
                    raise ValueError("Original diagnostic phase is immutable")
                return
            _publish(fd, name + ".pending", name, raw)
        finally:
            os.close(fd)

    async def load_exact(
        self, reference: DiagnosticRef, identity: DiagnosticIdentity
    ) -> ProcessDiagnostic | FinalizationDiagnostic:
        value = DiagnosticRef.model_validate(reference.model_dump())
        if value.identity != identity:
            raise ValueError("Diagnostic original identity differs")
        raw = await asyncio.to_thread(self._read, self.filename(identity, value.phase))
        if len(raw) != value.byte_length or hashlib.sha256(raw).hexdigest() != value.sha256:
            raise ValueError("Diagnostic actual bytes differ")
        decoded = json.loads(raw, object_pairs_hook=_unique_pairs)
        record = (
            ProcessDiagnostic.model_validate_json(raw)
            if decoded.get("phase_kind") == "raw"
            else FinalizationDiagnostic.model_validate_json(raw)
        )
        if record.identity != identity or record.phase_kind != value.phase:
            raise ValueError("Diagnostic stored original phase differs")
        return record

    def _read(self, name: str) -> bytes:
        fd = _directory(self.root, self._root_identity)
        try:
            return _read_file(fd, name)
        finally:
            os.close(fd)


def _record(value: dict[str, object]) -> ProcessDiagnostic | FinalizationDiagnostic:
    if value.get("phase_kind") == "raw":
        return ProcessDiagnostic.model_validate(value)
    if value.get("phase_kind") == "final":
        return FinalizationDiagnostic.model_validate(value)
    raise ValueError("Unknown diagnostic record cannot select a phase")


def error_kind(failure: BaseException | None) -> ErrorKind:
    from pydantic import ValidationError

    if failure is None:
        return "none"
    if type(failure).__name__ == "DiscoveryUnavailableError":
        return "DiscoveryUnavailableError"
    if isinstance(failure, asyncio.CancelledError):
        return "CancelledError"
    if isinstance(failure, ValidationError):
        return "ValidationError"
    if isinstance(failure, TimeoutError):
        return "TimeoutError"
    if isinstance(failure, OSError):
        return "OSError"
    if isinstance(failure, ValueError):
        return "ValueError"
    return "other"


def interruption_kind(
    value: str | None,
) -> ErrorKind | Literal["capture_or_reap_unresolved"] | None:
    """Only controlled interruption labels survive; original capture strings remain unchanged."""
    allowed = {
        "none",
        "DiscoveryUnavailableError",
        "ValueError",
        "ValidationError",
        "OSError",
        "TimeoutError",
        "CancelledError",
        "other",
        "capture_or_reap_unresolved",
    }
    normalized = value if value is None or value in allowed else "other"
    return cast(ErrorKind | Literal["capture_or_reap_unresolved"] | None, normalized)
