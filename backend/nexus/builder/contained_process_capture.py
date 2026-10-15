"""Original raw capture assembly; explicit pre/post placement binding is added separately."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Literal

from nexus.builder import contained_process_contracts as contracts
from nexus.builder.contained_contracts import HostPlacementIdentity
from nexus.builder.contained_evidence_types import (
    ExactContainer,
    ObservationDeadline,
    ObservedSample,
)
from nexus.builder.contained_process_contracts import (
    ContainedRunCapture,
    ProcessRunBinding,
    ProcessSampling,
    StartedContainedProcess,
    process_diagnostic,
)
from nexus.builder.process import ProcessCapture


class _Prefix:
    """Keep at most the original cap, including when overflow or cancellation interrupts capture."""

    def __init__(self, limit: int) -> None:
        self.limit, self.body = limit, bytearray()

    async def read(self, stream: asyncio.StreamReader) -> bytes:
        while part := await stream.read(min(65536, self.limit - len(self.body) + 1)):
            remaining = self.limit - len(self.body)
            self.body.extend(part[:remaining])
            if len(part) > remaining:
                raise ValueError("Contained original output exceeds cap; prefix retained")
        return bytes(self.body)


# Original >50-line capture transaction preserves post-CPU checks and matching diagnostics together.
def _capture(
    started: StartedContainedProcess,
    deadline: ObservationDeadline,
    sealed: ExactContainer | None,
    samples: list[ObservedSample],
    stdout_prefix: _Prefix,
    stderr_prefix: _Prefix,
    wait: asyncio.Task[int],
    elapsed_millis: int,
    reason: str | None,
    uncertain: bool,
    clock: Callable[[], int],
    binding: ProcessRunBinding,
    state: ProcessSampling,
) -> ContainedRunCapture:
    process = started.process
    capture = ProcessCapture(
        stdout=bytes(stdout_prefix.body),
        stderr=bytes(stderr_prefix.body),
        exit_code=process.returncode if process.returncode is not None else -1,
        elapsed_millis=elapsed_millis,
        interruption=reason or ("capture_or_reap_unresolved" if uncertain else None),
    )
    result = assemble_capture(
        started,
        deadline,
        sealed,
        samples,
        capture,
        wait,
        reason,
        uncertain,
        issued_identity=state.issued_identity,
        issued_cleanup=state.issued_cleanup,
    )
    result = result.model_copy(
        update={
            "parent_attempt": state.parent_attempt,
            "issued_identity": state.issued_identity,
            "issued_cleanup": state.issued_cleanup,
        }
    )
    result = result.model_copy(update={"diagnostic": process_diagnostic(binding, result, state)})
    if clock() >= min(deadline.end_us, started.parent.deadline_us):
        diagnostic = result.diagnostic
        assert diagnostic is not None
        return result.model_copy(
            update={
                "infrastructure": "unresolved",
                "limitations": ("shared_deadline_expired",),
                "diagnostic": diagnostic.model_copy(
                    update={
                        "infrastructure": "unresolved",
                        "phase": "capture",
                        "error_type": "TimeoutError",
                    }
                ),
            }
        )
    return result


def assemble_capture(
    started: StartedContainedProcess,
    deadline: ObservationDeadline,
    sealed: ExactContainer | None,
    samples: list[ObservedSample],
    capture: ProcessCapture,
    wait: asyncio.Task[int],
    reason: str | None,
    uncertain: bool,
    *,
    issued_identity: HostPlacementIdentity | None = None,
    issued_cleanup: Literal["closed", "deferred"] | None = None,
) -> ContainedRunCapture:
    """Assemble existing capture semantics; diagnostics add no new success predicate."""
    complete = (
        sealed is not None
        and bool(samples)
        and all(row.status == "observed_contained" for row in samples)
    )
    result = contracts.ContainedRunCapture(
        capture=capture,
        runtime=started.runtime(wait),
        parent=started.parent,
        deadline=deadline,
        sealed_container=sealed,
        samples=tuple(samples),
        infrastructure="unresolved" if uncertain or reason else "known" if complete else "unproven",
        limitations=(() if complete and not reason else ("host_containment_unproven",)),
        issued_identity=issued_identity,
        issued_cleanup=issued_cleanup,
    )
    return result
