"""Fixed known-container cleanup IO; native receipt/fence authorization belongs to Root caller."""

from __future__ import annotations

import asyncio
import json
from typing import Literal, Self
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from nexus.builder.contained_contracts import ContainedValue, Positive
from nexus.builder.contained_process_contracts import OwnedName
from nexus.builder.contained_query import clock_us
from nexus.builder.contracts import Digest
from nexus.builder.process import engine_environment

CleanupKind = Literal["inventory", "inspect", "remove"]
CLEANUP_VERSION = "nexus.builder.contained-cleanup.v1"
CLEANUP_TOTAL_US = 5_000_000
CLEANUP_REAP_RESERVE_US = 100_000
CLEANUP_INVENTORY_ROWS = 512
CLEANUP_STDOUT_BYTES = 65536
CLEANUP_STDERR_BYTES = 4096
PREFIX = ("/usr/bin/podman", "--remote=false", "--cgroup-manager=cgroupfs")
INVENTORY_FORMAT = '{"container_id":{{json .ID}},"container_name":{{json .Names}}}'
STOPPED_FORMAT = (
    '{"container_id":{{json .Id}},"container_name":{{json .Name}},"image_id":{{json .Image}},'
    '"company_id":{{json (index .Config.Labels "nexus.builder.company")}},'
    '"action_id":{{json (index .Config.Labels "nexus.builder.action")}},'
    '"running":{{json .State.Running}}}'
)


class CleanupIdentity(ContainedValue):
    """Root derives this from actual saved native evidence; the DTO is not a cleanup permit."""

    company_id: UUID
    action_id: UUID
    container_name: OwnedName
    container_id: Digest
    image_id: Digest

    @model_validator(mode="after")
    def native_name(self) -> Self:
        if (
            self.container_name
            != "nexus-builder-" + uuid5(self.company_id, str(self.action_id)).hex
        ):
            raise ValueError("Cleanup object is not the exact original native name")
        return self


class CleanupDeadline(ContainedValue):
    """One original operation end, at most5s including100ms reap; never reset between phases."""

    started_us: Positive
    end_us: Positive

    @model_validator(mode="after")
    def finite_original(self) -> Self:
        if not 0 < self.end_us - self.started_us <= CLEANUP_TOTAL_US:
            raise ValueError("Cleanup original total budget exceeds5seconds or is empty")
        return self

    @classmethod
    def start(cls) -> CleanupDeadline:
        now = clock_us()
        return cls(started_us=now, end_us=now + CLEANUP_TOTAL_US)


class CleanupCommandCapture(ContainedValue):
    """Actual owned command output prefixes, not a report that native cleanup was authorized."""

    kind: CleanupKind
    child_pid: Positive
    stdout: bytes = Field(max_length=CLEANUP_STDOUT_BYTES)
    stderr: bytes = Field(max_length=CLEANUP_STDERR_BYTES)
    exit_code: int | None
    reaped: bool
    complete: bool
    overflow: bool


class CleanupInspection(ContainedValue):
    """Only complete exact inventory/inspection bytes qualify stopped or absent state."""

    expected: CleanupIdentity
    state: Literal["absent", "stopped"]
    inventory: CleanupCommandCapture
    inspection: CleanupCommandCapture | None = None

    @model_validator(mode="after")
    def complete_actual_bytes(self) -> Self:
        _successful(self.inventory, "inventory")
        present = decode_inventory(self.inventory.stdout, self.expected)
        if self.state == "absent":
            if present or self.inspection is not None:
                raise ValueError("Cleanup absence contradicts complete inventory")
        else:
            if not present or self.inspection is None:
                raise ValueError("Cleanup stopped state lacks complete inventory/inspection")
            _successful(self.inspection, "inspect")
            decode_stopped(self.inspection.stdout, self.expected)
        return self


class _InventoryRow(ContainedValue):
    container_id: Digest
    container_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class _StoppedObject(CleanupIdentity):
    running: bool


class CleanupUnresolvedError(ValueError):
    """Preserve exact child/pending task and prefixes when a transport may have run."""

    def __init__(
        self,
        message: str,
        *,
        capture: CleanupCommandCapture | None = None,
        pending: asyncio.Task[asyncio.subprocess.Process] | None = None,
        process: asyncio.subprocess.Process | None = None,
        previous: tuple[CleanupCommandCapture, ...] = (),
    ) -> None:
        super().__init__(message)
        self.capture, self.pending, self.process = capture, pending, process
        self.previous = previous


def cleanup_argv(kind: str, expected: CleanupIdentity) -> tuple[str, ...]:
    value = CleanupIdentity.model_validate(expected.model_dump())
    if kind == "inventory":
        return (*PREFIX, "ps", "--all", "--no-trunc", "--format", INVENTORY_FORMAT)
    if kind == "inspect":
        return (*PREFIX, "inspect", "--format", STOPPED_FORMAT, value.container_id)
    if kind == "remove":
        return (*PREFIX, "rm", value.container_id)
    raise ValueError("Unknown cleanup operation cannot select an engine command")


def decode_inventory(raw: bytes, expected: CleanupIdentity) -> bool:
    value = CleanupIdentity.model_validate(expected.model_dump())
    if len(raw) > CLEANUP_STDOUT_BYTES or len(raw.splitlines()) > CLEANUP_INVENTORY_ROWS:
        raise ValueError("Cleanup complete inventory exceeds byte/count bound")
    ids: set[str] = set()
    names: set[str] = set()
    for line in raw.splitlines():
        json.loads(line, object_pairs_hook=_unique)
        row = _InventoryRow.model_validate_json(line)
        if row.container_id in ids or row.container_name in names:
            raise ValueError("Cleanup complete inventory has duplicate identity/name")
        ids.add(row.container_id)
        names.add(row.container_name)
        if (row.container_id == value.container_id) != (row.container_name == value.container_name):
            raise ValueError("Cleanup immutable ID/native-name association changed")
    return value.container_id in ids


def decode_stopped(raw: bytes, expected: CleanupIdentity) -> CleanupIdentity:
    value = CleanupIdentity.model_validate(expected.model_dump())
    if len(raw) > CLEANUP_STDOUT_BYTES:
        raise ValueError("Cleanup exact inspection exceeds complete byte bound")
    json.loads(raw, object_pairs_hook=_unique)
    observed = _StoppedObject.model_validate_json(raw)
    if (
        observed.running is not False
        or observed.model_dump(exclude={"running"}) != value.model_dump()
    ):
        raise ValueError("Cleanup stopped object identity/image/labels changed")
    return value


class _Prefix:
    def __init__(self, limit: int) -> None:
        self.limit, self.body, self.overflow = limit, bytearray(), False

    async def read(self, pipe: asyncio.StreamReader) -> None:
        while part := await pipe.read(min(65536, self.limit - len(self.body) + 1)):
            remaining = self.limit - len(self.body)
            self.body.extend(part[:remaining])
            if len(part) > remaining:
                self.overflow = True
                raise ValueError("Cleanup command output exceeds cap; prefix retained")


class ContainedCleanup:
    """Fixed infrastructure IO only; no native authorization or combined delete."""

    async def inspect_stopped(
        self, expected: CleanupIdentity, deadline: CleanupDeadline
    ) -> CleanupInspection:
        listing = await self._call("inventory", expected, deadline)
        inspected = None
        try:
            present = decode_inventory(listing.stdout, expected)
            inspected = await self._call("inspect", expected, deadline) if present else None
            result = CleanupInspection(
                expected=expected,
                state="stopped" if present else "absent",
                inventory=listing,
                inspection=inspected,
            )
            _remaining(deadline)
            return result
        except CleanupUnresolvedError as failure:
            failure.previous = (listing,)
            raise
        except (ValueError, TimeoutError) as failure:
            raise CleanupUnresolvedError(
                "Cleanup inspection bytes remain unresolved",
                capture=inspected or listing,
                previous=(listing,) if inspected else (),
            ) from failure

    async def remove_stopped(
        self, captured: CleanupInspection, deadline: CleanupDeadline
    ) -> CleanupCommandCapture:
        # Root rechecks actual native receipt/current fence AFTER inspect and BEFORE this call.
        value = CleanupInspection.model_validate(captured.model_dump())
        if value.state != "stopped":
            raise ValueError("Cleanup absent inventory cannot select removal")
        result = await self._call("remove", value.expected, deadline)
        if result.stdout.strip() != value.expected.container_id.encode("ascii"):
            raise CleanupUnresolvedError(
                "Cleanup rm returned another or incomplete identity", capture=result
            )
        _require_terminal_clock(deadline, result)
        return result

    async def _call(
        self, kind: CleanupKind, expected: CleanupIdentity, deadline: CleanupDeadline
    ) -> CleanupCommandCapture:
        argv, environment = cleanup_argv(kind, expected), engine_environment()
        _remaining(deadline, reserve=CLEANUP_REAP_RESERVE_US)
        pending = asyncio.create_task(_issue(argv, environment, deadline))
        process: asyncio.subprocess.Process | None = None
        out, err = _Prefix(CLEANUP_STDOUT_BYTES), _Prefix(CLEANUP_STDERR_BYTES)
        tasks: list[asyncio.Task[None] | asyncio.Task[int]] = []
        failure: BaseException | None = None
        try:
            async with asyncio.timeout(_remaining(deadline, reserve=CLEANUP_REAP_RESERVE_US)):
                process = await asyncio.shield(pending)
                assert process.stdout is not None and process.stderr is not None
                tasks = [
                    asyncio.create_task(out.read(process.stdout)),
                    asyncio.create_task(err.read(process.stderr)),
                    asyncio.create_task(process.wait()),
                ]
                await asyncio.gather(*tasks)
        except (Exception, asyncio.CancelledError) as caught:
            failure = caught
        if process is None:
            process = await _obtain(pending, deadline)
        reaped = await _reap(process, tasks, deadline)
        capture = CleanupCommandCapture(
            kind=kind,
            child_pid=process.pid,
            stdout=bytes(out.body),
            stderr=bytes(err.body),
            exit_code=process.returncode,
            reaped=reaped,
            complete=failure is None
            and len(tasks) == 3
            and all(
                task.done() and not task.cancelled() and task.exception() is None for task in tasks
            ),
            overflow=out.overflow or err.overflow,
        )
        if failure is not None:
            raise CleanupUnresolvedError(
                "Cleanup command interrupted; preserve uncertainty",
                capture=capture,
                process=process,
            ) from failure
        _successful(capture, kind)
        _require_terminal_clock(deadline, capture)
        return capture


async def _issue(
    argv: tuple[str, ...], environment: dict[str, str], deadline: CleanupDeadline
) -> asyncio.subprocess.Process:
    _remaining(
        deadline, reserve=CLEANUP_REAP_RESERVE_US
    )  # Fresh inside scheduled task, no IO before exact spawn.
    return await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )


async def _obtain(
    pending: asyncio.Task[asyncio.subprocess.Process], deadline: CleanupDeadline
) -> asyncio.subprocess.Process:
    try:
        async with asyncio.timeout(_remaining(deadline)):
            return await asyncio.shield(pending)
    except (Exception, asyncio.CancelledError) as failure:
        pending.add_done_callback(_consume)
        raise CleanupUnresolvedError(
            "Cleanup child handle remains unresolved", pending=pending
        ) from failure


async def _reap(
    process: asyncio.subprocess.Process,
    tasks: list[asyncio.Task[None] | asyncio.Task[int]],
    deadline: CleanupDeadline,
) -> bool:
    try:
        async with asyncio.timeout(_remaining(deadline)):
            if process.returncode is None:
                process.kill()  # Exact unreaped child only; never a payload/container/scope kill.
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await process.wait()
            return True
    except (OSError, TimeoutError):
        for task in tasks:
            if not task.done():
                task.cancel()
        return False


def _successful(capture: CleanupCommandCapture, kind: CleanupKind) -> None:
    value = CleanupCommandCapture.model_validate(capture.model_dump())
    if (
        value.kind != kind
        or value.exit_code != 0
        or not value.reaped
        or not value.complete
        or value.overflow
    ):
        raise CleanupUnresolvedError(
            "Cleanup command has no complete successful capture", capture=value
        )


def _require_terminal_clock(deadline: CleanupDeadline, capture: CleanupCommandCapture) -> None:
    try:
        _remaining(deadline)
    except TimeoutError as failure:
        raise CleanupUnresolvedError(
            "Cleanup result returned after its original end", capture=capture
        ) from failure


def _remaining(deadline: CleanupDeadline, *, reserve: int = 0) -> float:
    value = CleanupDeadline.model_validate(deadline.model_dump())
    now = clock_us()
    if not value.started_us <= now < value.end_us - reserve:
        raise TimeoutError("Cleanup original total deadline expired or clock regressed")
    return (value.end_us - reserve - now) / 1_000_000


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Cleanup JSON repeats a field")
        result[key] = value
    return result


def _consume(task: asyncio.Task[asyncio.subprocess.Process]) -> None:
    if not task.cancelled():
        task.exception()
