"""Bounded current-call parent metadata describes failures and never grants a parent permit."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from typing import Literal, Self

from pydantic import Field, ValidationError, model_validator

from nexus.builder.contained_contracts import (
    ContainedValue,
    HostPlacementIdentity,
    KernelScopeFacts,
    Positive,
    ScopeExpectation,
    SystemdScopeFacts,
    UInt,
)
from nexus.builder.contracts import Digest

ParentStage = Literal[
    "manager_uid",
    "manager_version",
    "manager_validate",
    "resolve",
    "unit",
    "scope",
    "unit_decode",
    "kernel",
    "validate",
    "complete",
    "issued_membership",
]
ParentError = Literal[
    "none",
    "ValueError",
    "ValidationError",
    "OSError",
    "TimeoutError",
    "CancelledError",
    "other",
]
ParentCode = Literal["none", "failed_at_stage", "deadline", "cancelled"]


class ParentQuery(ContainedValue):
    index: int = Field(ge=0, le=4, strict=True)
    argv_sha256: Digest
    observed_bytes: UInt | None
    observed_sha256: Digest | None
    prefix_base64: str | None = Field(max_length=684)
    complete: bool
    overflow: bool
    error_type: ParentError = "none"

    @model_validator(mode="after")
    def observed_only(self) -> Self:
        if self.observed_bytes is None:
            if (
                self.observed_sha256 is not None
                or self.prefix_base64 is not None
                or self.complete
                or self.overflow
            ):
                raise ValueError("Unreturned query bytes must remain unknown")
        else:
            if self.observed_sha256 is None or self.prefix_base64 is None:
                raise ValueError("Observed query metadata is incomplete")
            prefix = base64.b64decode(self.prefix_base64, validate=True)
            if len(prefix) > min(512, self.observed_bytes) or self.observed_bytes > 16385:
                raise ValueError("Parent query metadata exceeds its fixed cap")
            if self.overflow and self.complete:
                raise ValueError("Overflow cannot claim a complete query")
        return self


class FactsDigest(ContainedValue):
    encoding: Literal["canonical-parsed-parent-facts.v1"] = "canonical-parsed-parent-facts.v1"
    byte_length: UInt
    sha256: Digest


class ParentAttempt(ContainedValue):
    ordinal: Positive
    started_us: UInt
    finished_us: UInt
    expectation_sha256: Digest
    stage: ParentStage
    queries: tuple[ParentQuery, ...] = Field(max_length=5)
    unit: SystemdScopeFacts | None
    kernel: KernelScopeFacts | None
    error_type: ParentError
    code: ParentCode
    unit_observed: FactsDigest | None
    kernel_observed: FactsDigest | None
    facts_truncated: bool
    issued_identity: HostPlacementIdentity | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def ordered_bounded_metadata(self) -> Self:
        if self.finished_us < self.started_us or tuple(q.index for q in self.queries) != tuple(
            range(len(self.queries))
        ):
            raise ValueError("Parent attempt metadata clock/query order differs")
        if (self.error_type == "none") != (self.code == "none"):
            raise ValueError("Parent diagnostic error/code differs")
        if self.code == "none" and (
            self.stage != "complete"
            or self.unit is None
            or self.kernel is None
            or len(self.queries) != 5
            or self.facts_truncated
        ):
            raise ValueError("Completed metadata lacks actual facts")
        for fact, digest in ((self.unit, self.unit_observed), (self.kernel, self.kernel_observed)):
            if fact is not None and digest != facts_digest(fact):
                raise ValueError("Parent diagnostic actual facts digest differs")
            if fact is None and digest is not None and not self.facts_truncated:
                raise ValueError("Parent diagnostic omitted facts lack explicit truncation")
        return self


class ParentRecorder:
    """One trusted call owns these observations; reset before the next provider read."""

    def __init__(self, ordinal: int, expected: ScopeExpectation, started_us: int) -> None:
        self.ordinal, self.started_us = ordinal, started_us
        self.expectation_sha256 = hashlib.sha256(expected.model_dump_json().encode()).hexdigest()
        self.stage: ParentStage = "manager_uid"
        self.code: ParentCode = "none"
        self.queries: list[ParentQuery] = []
        self.unit: SystemdScopeFacts | None = None
        self.kernel: KernelScopeFacts | None = None
        self.issued_identity: HostPlacementIdentity | None = None

    def begin_query(self, index: int, argv: tuple[str, ...]) -> None:
        if index != len(self.queries) or index >= 5:
            raise ValueError("Parent diagnostic query sequence differs")
        self.queries.append(
            ParentQuery(
                index=index,
                argv_sha256=hashlib.sha256(
                    json.dumps(argv, separators=(",", ":")).encode()
                ).hexdigest(),
                observed_bytes=None,
                observed_sha256=None,
                prefix_base64=None,
                complete=False,
                overflow=False,
            )
        )

    def reply(self, raw: bytes) -> None:
        observed = raw[:16385]
        self.queries[-1] = self.queries[-1].model_copy(
            update={
                "observed_bytes": len(observed),
                "observed_sha256": hashlib.sha256(observed).hexdigest(),
                "prefix_base64": base64.b64encode(observed[:512]).decode(),
                "complete": len(raw) <= 16384,
                "overflow": len(raw) > 16384,
            }
        )

    def query_failed(self, failure: BaseException) -> None:
        self.queries[-1] = self.queries[-1].model_copy(update={"error_type": parent_error(failure)})

    def finish(self, failure: BaseException | None, finished_us: int) -> ParentAttempt:
        kind = parent_error(failure)
        code: ParentCode = (
            "none"
            if failure is None
            else self.code
            if self.code != "none"
            else "cancelled"
            if kind == "CancelledError"
            else "deadline"
            if kind == "TimeoutError"
            else "failed_at_stage"
        )
        unit, unit_digest, unit_large = bounded_facts(self.unit, 16384)
        kernel, kernel_digest, kernel_large = bounded_facts(self.kernel, 8192)
        return ParentAttempt.model_validate(
            {
                "ordinal": self.ordinal,
                "started_us": self.started_us,
                "finished_us": finished_us,
                "expectation_sha256": self.expectation_sha256,
                "stage": self.stage,
                "queries": tuple(q.model_dump() for q in self.queries),
                "unit": unit,
                "kernel": kernel,
                "unit_observed": unit_digest.model_dump() if unit_digest else None,
                "kernel_observed": kernel_digest.model_dump() if kernel_digest else None,
                "facts_truncated": unit_large or kernel_large,
                "issued_identity": self.issued_identity.model_dump()
                if self.issued_identity
                else None,
                "error_type": kind,
                "code": code,
            }
        )


def facts_digest(value: SystemdScopeFacts | KernelScopeFacts) -> FactsDigest:
    fields = value.model_dump(mode="json")
    if isinstance(value, KernelScopeFacts):
        fields["controllers"] = sorted(value.controllers)
    raw = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return FactsDigest(byte_length=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def bounded_facts(
    value: SystemdScopeFacts | KernelScopeFacts | None, limit: int
) -> tuple[dict[str, object] | None, FactsDigest | None, bool]:
    if value is None:
        return None, None, False
    digest = facts_digest(value)
    return (
        None if digest.byte_length > limit else value.model_dump(),
        digest,
        digest.byte_length > limit,
    )


def parent_error(failure: BaseException | None) -> ParentError:
    if failure is None:
        return "none"
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


def failure_parent_attempt(
    failure: BaseException, expected: ScopeExpectation
) -> ParentAttempt | None:
    """Only the actual exception's failed current call is copied; no provider cache is authority."""
    record = getattr(failure, "nexus_parent_attempt", None)
    if record is None:
        return None
    if not isinstance(record, ParentAttempt):
        raise ValueError("Parent exception metadata type differs")
    value = ParentAttempt.model_validate(record.model_dump())
    if (
        value.error_type == "none"
        or value.expectation_sha256
        != hashlib.sha256(expected.model_dump_json().encode()).hexdigest()
    ):
        raise ValueError("Parent failure metadata binds another scope or successful call")
    return value
