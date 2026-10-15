"""Private observed-only owned-membership failures; metadata never grants authority."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from dataclasses import dataclass
from typing import Literal, Self, TypeVar
from uuid import UUID

from pydantic import Field, ValidationError, model_validator

from nexus.builder.contained_contracts import ContainedValue, Positive, ScopeExpectation, UInt
from nexus.builder.contracts import Digest

Step = Literal[
    "context_check",
    "io_deadline",
    "runtime_initial",
    "seal_binding",
    "before_membership",
    "collector_before",
    "runtime_before",
    "boot_uid_mount",
    "root_open",
    "root_identity",
    "leaf_open",
    "leaf_identity",
    "held_leaf",
    "visible_leaf",
    "root_recheck",
    "collector_after",
    "runtime_after",
    "after_membership",
    "root_visible_after",
    "mount_after",
    "kernel_placement",
    "stable_identity",
]
Kind = Literal[
    "ValueError", "ValidationError", "OSError", "TimeoutError", "CancelledError", "other"
]
FieldName = Literal[
    "closed",
    "runtime_present",
    "runtime_pid",
    "runtime_returncode",
    "runtime_start",
    "collector_pid",
    "collector_before",
    "runtime_before",
    "collector_after",
    "runtime_after",
    "boot_id",
    "uid",
    "mount_id",
    "root",
    "leaf",
    "visible_leaf",
    "root_known",
    "runtime_returncode_after",
    "closed_after",
]
T = TypeVar("T")


class ProcObserved(ContainedValue):
    start_ticks: Positive
    cgroup_path: str = Field(min_length=1, max_length=4096)


class DirectoryObserved(ContainedValue):
    device: UInt
    inode: Positive
    uid: UInt
    mount_id: Positive | None


class Operands(ContainedValue):
    closed: bool | None = None
    runtime_present: bool | None = None
    runtime_pid: Positive | None = None
    runtime_returncode_observed: bool = False
    runtime_returncode: int | None = Field(default=None, strict=True)
    runtime_start: Positive | None = None
    collector_pid: Positive | None = None
    collector_before: ProcObserved | None = None
    runtime_before: ProcObserved | None = None
    collector_after: ProcObserved | None = None
    runtime_after: ProcObserved | None = None
    boot_id: UUID | None = None
    uid: UInt | None = None
    mount_id: Positive | None = None
    root: DirectoryObserved | None = None
    leaf: DirectoryObserved | None = None
    visible_leaf: DirectoryObserved | None = None
    root_known: bool | None = None
    runtime_returncode_after_observed: bool = False
    runtime_returncode_after: int | None = Field(default=None, strict=True)
    closed_after: bool | None = None


class IssuedFailure(ContainedValue):
    schema_version: Literal["nexus.builder.issued-failure.v1"] = "nexus.builder.issued-failure.v1"
    expectation_sha256: Digest
    binding_sha256: Digest
    step: Step
    observed_us: UInt
    original_end_us: Positive
    error_type: Kind
    errno: int | None = Field(default=None, ge=0, le=4095, strict=True)
    operands: Operands | None
    observed_bytes: UInt | None
    observed_sha256: Digest | None
    truncated: bool
    metadata_unavailable: bool = False

    @model_validator(mode="after")
    def observed_only(self) -> Self:
        if self.metadata_unavailable:
            if (
                self.operands is not None
                or self.observed_bytes is not None
                or self.observed_sha256 is not None
                or self.truncated
            ):
                raise ValueError("Unavailable issued metadata cannot invent observations")
        elif self.operands is None:
            if not self.truncated or self.observed_bytes is None or self.observed_sha256 is None:
                raise ValueError("Missing issued operands require explicit truncation")
        else:
            raw = self.operands.model_dump_json().encode()
            if (
                self.truncated
                or len(raw) != self.observed_bytes
                or _sha(raw) != self.observed_sha256
            ):
                raise ValueError("Issued operands differ from actual observed metadata")
        if len(self.model_dump_json().encode()) > 4096:
            raise ValueError("Issued failure exceeds four KiB")
        return self


@dataclass(frozen=True)
class _Attached:
    failure: BaseException
    token: object
    value: IssuedFailure


class FailureRecorder:
    """One call keeps existing-read values; a timeout snapshot never backfills late worker facts."""

    def __init__(self, expected: ScopeExpectation, binding_sha: str, end: int) -> None:
        self.expected_sha = _sha(expected.model_dump_json().encode())
        self.binding_sha, self.end = binding_sha, end
        self.step: Step = "context_check"
        self._values: dict[str, object] = {}
        self._lock = threading.Lock()

    def mark(self, step: Step) -> None:
        with self._lock:
            self.step = step

    def remember(self, key: FieldName, value: T) -> T:
        with self._lock:
            if isinstance(value, tuple) and key in (
                "collector_before",
                "runtime_before",
                "collector_after",
                "runtime_after",
            ):
                self._values[key] = {"start_ticks": value[0], "cgroup_path": value[1]}
            elif isinstance(value, tuple) and key in ("root", "leaf", "visible_leaf"):
                self._values[key] = dict(
                    zip(("device", "inode", "uid", "mount_id"), value, strict=True)
                )
            else:
                self._values[key] = value
            if key in ("runtime_returncode", "runtime_returncode_after"):
                self._values[key + "_observed"] = True
        return value

    def attach(self, failure: BaseException, token: object, now: int) -> None:
        with self._lock:
            step, values = self.step, dict(self._values)
        try:
            operands = Operands.model_validate(values)
            raw = operands.model_dump_json().encode()
        except (TypeError, ValueError):
            operands, raw = (
                None,
                None,
            )  # Preserve original failure; unavailable facts are not invented.
        value = IssuedFailure(
            expectation_sha256=self.expected_sha,
            binding_sha256=self.binding_sha,
            step=step,
            observed_us=now,
            original_end_us=self.end,
            error_type=_kind(failure),
            errno=failure.errno if isinstance(failure, OSError) else None,
            operands=operands if raw is not None and len(raw) <= 3000 else None,
            observed_bytes=len(raw) if raw is not None else None,
            observed_sha256=_sha(raw) if raw is not None else None,
            truncated=raw is not None and len(raw) > 3000,
            metadata_unavailable=raw is None,
        )
        failure.__dict__["nexus_issued_failure"] = _Attached(failure, token, value)


def issued_failure(
    failure: BaseException,
    token: object,
    expected: ScopeExpectation,
    started: int,
    ended: int,
) -> IssuedFailure | None:
    """Only this exact exception/token/current expected call can supply its own metadata."""
    attached = failure.__dict__.get("nexus_issued_failure")
    if (
        not isinstance(attached, _Attached)
        or attached.failure is not failure
        or attached.token is not token
    ):
        return None
    value = IssuedFailure.model_validate(attached.value.model_dump())
    if (
        value.expectation_sha256 != _sha(expected.model_dump_json().encode())
        or not started <= value.observed_us <= ended
    ):
        return None
    return value


def _kind(failure: BaseException) -> Kind:
    if isinstance(failure, asyncio.CancelledError):
        return "CancelledError"
    if isinstance(failure, TimeoutError):
        return "TimeoutError"
    if isinstance(failure, OSError):
        return "OSError"
    if isinstance(failure, ValidationError):
        return "ValidationError"
    return "ValueError" if isinstance(failure, ValueError) else "other"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
