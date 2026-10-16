"""Stop only an original opaque sealed object; engine stop is not whole-tree qualification."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from nexus.builder.contained_contracts import ContainedValue
from nexus.builder.contained_evidence_types import ExactContainer, ObservationDeadline
from nexus.builder.contained_issued_context import OwnedIssuedContext
from nexus.builder.contained_owned_stop_io import (
    STOP_STDOUT_BYTES,
    STOP_TOTAL_US,
    OwnedStopIO,
    StopCapture,
    require_owner,
)
from nexus.builder.contained_process_contracts import ProcessRunBinding, StartedContainedProcess
from nexus.builder.contained_query import clock_us
from nexus.builder.contracts import Digest

OWNED_STOP_VERSION = "nexus.builder.contained-owned-stop.v1"


class _Inspected(ContainedValue):
    container_id: Digest
    container_name: str
    image_id: Digest
    company_id: UUID
    action_id: UUID
    running: bool


@dataclass(frozen=True)
class StopResult:
    """Complete engine termination metadata, not a permit or observed descendant retirement."""

    container: ExactContainer
    entered_us: int
    end_us: int
    finished_us: int
    captures: tuple[StopCapture, ...]


def decode_inspection(raw: bytes, expected: ExactContainer) -> bool:
    if len(raw) > STOP_STDOUT_BYTES:
        raise ValueError("Owned stop exact inspection exceeds the fixed complete byte cap")
    json.loads(raw, object_pairs_hook=_unique)
    row = _Inspected.model_validate_json(raw)
    if (row.container_id, row.container_name, row.image_id, row.company_id, row.action_id) != (
        expected.container_id,
        expected.container_name,
        expected.image_id,
        expected.company_id,
        expected.action_id,
    ):
        raise ValueError("Owned stop exact immutable object changed")
    return row.running


class ContainedOwnedStop:
    """The concrete process owns this one-shot cleanup boundary; no remove/new effect."""

    def __init__(self, *, clock: Callable[[], int] = clock_us) -> None:
        self.clock, self.io = clock, OwnedStopIO(clock=clock)
        self._used: dict[OwnedIssuedContext, StopResult | BaseException | None] = {}

    async def stop(
        self,
        context: OwnedIssuedContext,
        started: StartedContainedProcess,
        binding: ProcessRunBinding,
        deadline: ObservationDeadline,
    ) -> StopResult:
        entered = self.clock()
        if started.owned_start is None:
            raise ValueError("Unsealed original process cannot authorize an engine stop")
        # This cap only shortens an existing end. It never creates time after expiry,
        # and every command/await keeps this SAME end rather than another five seconds.
        end = min(
            deadline.end_us,
            started.parent.deadline_us,
            started.owned_start.end_us,
            entered + STOP_TOTAL_US,
        )
        expected = require_owner(context, started, binding, end)
        seal = context.seal
        io = self.io
        if type(io) is not OwnedStopIO:
            raise ValueError("Owned stop concrete transport differs")
        io.remaining(end)
        if context in self._used:
            raise ValueError("Original owned stop transaction cannot be repeated")
        context.claim_owned_stop(end)
        self._used[context] = None  # Original captures/owners stay private, including failed stops.
        captures: list[StopCapture] = []
        try:
            before = await io.call("inspect", context, started, binding, end)
            captures.append(before)
            self._current(io, context, seal, end)
            if decode_inspection(before.stdout, expected):
                killed = await io.call("kill", context, started, binding, end)
                captures.append(killed)
                self._current(io, context, seal, end)
                if killed.stdout.strip() != expected.container_id.encode("ascii"):
                    raise ValueError("Owned kill returned a foreign or incomplete ID")
            waited = await io.call("wait", context, started, binding, end)
            captures.append(waited)
            self._current(io, context, seal, end)
            if re.fullmatch(rb"-?[0-9]+\n?", waited.stdout) is None:
                raise ValueError("Owned wait did not return one bounded exit status")
            if not -1 <= int(waited.stdout) <= 255:
                raise ValueError("Owned wait exit status is unsupported")
            after = await io.call("postinspect", context, started, binding, end)
            captures.append(after)
            self._current(io, context, seal, end)
            if decode_inspection(after.stdout, expected):
                raise ValueError("Owned container is still running after stop/wait")
            require_owner(context, started, binding, end)
            self._current(io, context, seal, end)
            result = StopResult(expected, entered, end, self.clock(), tuple(captures))
            self._used[context] = result
            self._current(io, context, seal, end)
            return result
        except BaseException as failure:
            failure.__dict__["_nexus_owned_stop_captures"] = tuple(captures)
            self._used[context] = failure
            raise

    def _current(
        self, io: OwnedStopIO, context: OwnedIssuedContext, seal: object, end_us: int
    ) -> None:
        if self.io is not io or type(io) is not OwnedStopIO or context.seal is not seal:
            raise ValueError("Owned stop transport changed during the original operation")
        io.remaining(end_us)


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Owned stop inspection repeated a field")
        result[key] = value
    return result
