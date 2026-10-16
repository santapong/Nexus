"""Fixed full-ID controls retain every actual child and reader under one existing end."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal, cast

from nexus.builder.contained_evidence_types import ExactContainer
from nexus.builder.contained_issued_context import OwnedIssuedContext
from nexus.builder.contained_process_contracts import ProcessRunBinding, StartedContainedProcess
from nexus.builder.contained_query import clock_us
from nexus.builder.process import engine_environment

StopKind = Literal["inspect", "kill", "wait", "postinspect"]
STOP_TOTAL_US = 5_000_000
STOP_REAP_RESERVE_US = 100_000
STOP_STDOUT_BYTES = 65_536
STOP_STDERR_BYTES = 4_096
STOP_PREFIX = ("/usr/bin/podman", "--remote=false", "--cgroup-manager=cgroupfs")
STOP_INSPECT_FORMAT = (
    '{"container_id":{{json .ID}},"container_name":{{json .Name}},"image_id":{{json .Image}},'
    '"company_id":{{json (index .Config.Labels "nexus.builder.company")}},'
    '"action_id":{{json (index .Config.Labels "nexus.builder.action")}},'
    '"running":{{json .State.Running}}}'
)


@dataclass(frozen=True)
class StopCapture:
    kind: StopKind
    argv: tuple[str, ...]
    started_us: int
    finished_us: int
    child_pid: int
    stdout: bytes
    stderr: bytes
    exit_code: int | None
    complete: bool
    reaped: bool
    overflow: bool


@dataclass
class StopOwners:
    pending: asyncio.Task[asyncio.subprocess.Process]
    process: asyncio.subprocess.Process | None
    readers: tuple[asyncio.Future[object], ...] = ()
    retirement: asyncio.Task[None] | None = None

    def settled(self) -> bool:
        return (
            self.process is not None
            and self.process.returncode is not None
            and len(self.readers) == 3
            and all(row.done() and not row.cancelled() for row in self.readers)
            and (
                self.retirement is None
                or (
                    self.retirement.done()
                    and not self.retirement.cancelled()
                    and self.retirement.exception() is None
                )
            )
        )


class StopIOUnresolvedError(ValueError):
    """Actual strong handles and bounded captures survive without a retry permission."""

    def __init__(
        self, first: BaseException, owners: StopOwners, capture: StopCapture | None
    ) -> None:
        super().__init__("Owned stop command remains unproven")
        self.first, self.owners, self.capture = first, owners, capture


def stop_argv(kind: StopKind, container: ExactContainer) -> tuple[str, ...]:
    """Description only; actual issue separately requires the opaque original context."""
    if kind in ("inspect", "postinspect"):
        return (*STOP_PREFIX, "inspect", "--format", STOP_INSPECT_FORMAT, container.container_id)
    if kind == "kill":
        return (*STOP_PREFIX, "kill", "--signal=KILL", container.container_id)
    if kind == "wait":
        return (*STOP_PREFIX, "wait", container.container_id)
    raise ValueError("Owned stop kind cannot select another command")


def require_owner(
    context: OwnedIssuedContext,
    started: StartedContainedProcess,
    binding: ProcessRunBinding,
    end_us: int,
) -> ExactContainer:
    if type(context) is not OwnedIssuedContext or started.owned_start is None:
        raise ValueError("Owned stop needs the original opaque issued context")
    return context.require_owned_stop(started.owned_start, started.process, binding, end_us)


class _Prefix:
    def __init__(self, limit: int) -> None:
        self.limit, self.body, self.overflow, self.eof = limit, bytearray(), False, False

    async def read(self, pipe: asyncio.StreamReader) -> None:
        while part := await pipe.read(min(8192, self.limit + 1 - len(self.body))):
            available = self.limit - len(self.body)
            self.body.extend(part[:available])
            if len(part) > available:
                self.overflow = True
                raise ValueError("Owned stop complete command output exceeds cap")
        self.eof = True


class OwnedStopIO:
    """No inventory/name/removal selector and no action-supplied command callback."""

    def __init__(self, *, clock: Callable[[], int] = clock_us) -> None:
        self.clock = clock

    def remaining(self, end_us: int, reserve: int = 0) -> float:
        value = end_us - self.clock() - reserve
        if value <= 0:
            raise TimeoutError("Owned stop original end expired")
        return value / 1_000_000

    async def call(
        self,
        kind: StopKind,
        context: OwnedIssuedContext,
        started: StartedContainedProcess,
        binding: ProcessRunBinding,
        end_us: int,
    ) -> StopCapture:
        expected = require_owner(context, started, binding, end_us)
        argv, environment = stop_argv(kind, expected), engine_environment()
        self.remaining(end_us, STOP_REAP_RESERVE_US)

        async def issue() -> asyncio.subprocess.Process:
            current = require_owner(context, started, binding, end_us)
            if current is not expected:
                raise ValueError("Owned stop sealed object changed before scheduled issue")
            self.remaining(end_us, STOP_REAP_RESERVE_US)
            return await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
            )

        began = self.clock()
        pending = asyncio.create_task(issue())
        pending.add_done_callback(_consume)
        owners = StopOwners(pending, None)
        out, err = _Prefix(STOP_STDOUT_BYTES), _Prefix(STOP_STDERR_BYTES)
        failure: BaseException | None = None
        try:
            async with asyncio.timeout(self.remaining(end_us, STOP_REAP_RESERVE_US)):
                issued = owners.process = await asyncio.shield(pending)
                assert issued.stdout is not None and issued.stderr is not None
                tasks = (
                    asyncio.create_task(out.read(issued.stdout)),
                    asyncio.create_task(err.read(issued.stderr)),
                    asyncio.create_task(issued.wait()),
                )
                owners.readers = tuple(cast(asyncio.Future[object], row) for row in tasks)
                for task in tasks:
                    task.add_done_callback(_consume)
                await asyncio.shield(asyncio.gather(*tasks))
            self.remaining(end_us)
        except BaseException as error:
            failure = error
        if owners.process is None:
            try:
                async with asyncio.timeout(self.remaining(end_us)):
                    owners.process = await asyncio.shield(pending)
            except BaseException as error:
                failure = failure or error
        process = owners.process
        if process is not None and not owners.settled():
            if not owners.readers and self.clock() < end_us:
                assert process.stdout is not None and process.stderr is not None
                drains = (
                    asyncio.create_task(out.read(process.stdout)),
                    asyncio.create_task(err.read(process.stderr)),
                    asyncio.create_task(process.wait()),
                )
                owners.readers = tuple(cast(asyncio.Future[object], row) for row in drains)
                for task in drains:
                    task.add_done_callback(_consume)
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()  # Only this owned control CLI; never a PID-selected payload.
            try:
                async with asyncio.timeout(self.remaining(end_us)):
                    if owners.readers:
                        await asyncio.shield(
                            asyncio.gather(*owners.readers, return_exceptions=True)
                        )
                    else:
                        wait = asyncio.create_task(process.wait())
                        owners.readers = (cast(asyncio.Future[object], wait),)
                        wait.add_done_callback(_consume)
                        await asyncio.shield(wait)
            except BaseException as error:
                failure = failure or error
        capture = (
            StopCapture(
                kind,
                argv,
                began,
                self.clock(),
                process.pid,
                bytes(out.body),
                bytes(err.body),
                process.returncode,
                failure is None and out.eof and err.eof,
                owners.settled(),
                out.overflow or err.overflow,
            )
            if process is not None
            else None
        )
        if capture is None or (
            failure is not None
            or not capture.complete
            or not capture.reaped
            or capture.overflow
            or capture.exit_code != 0
            or capture.stderr
        ):
            original = failure or ValueError("Owned stop control has no successful complete reply")
            _retain_retirement(owners, out, err)
            unresolved = StopIOUnresolvedError(original, owners, capture)
            if isinstance(original, asyncio.CancelledError):
                original.__dict__["_nexus_owned_stop_io"] = unresolved
                raise original
            raise unresolved from original
        try:
            self.remaining(end_us)
        except BaseException as final_error:
            _retain_retirement(owners, out, err)
            raise StopIOUnresolvedError(final_error, owners, capture) from final_error
        return capture


def _consume[T](done: asyncio.Future[T]) -> None:
    if not done.cancelled():
        done.exception()


def _retain_retirement(owners: StopOwners, out: _Prefix, err: _Prefix) -> None:
    if not owners.settled() and owners.retirement is None:
        # Resource completion has no new observation/engine-command budget or result.
        owners.retirement = asyncio.create_task(_retire_issued_cli(owners, out, err))
        owners.retirement.add_done_callback(_consume)


async def _retire_issued_cli(owners: StopOwners, out: _Prefix, err: _Prefix) -> None:
    process = owners.process = await asyncio.shield(owners.pending)
    if process.returncode is None:
        with suppress(ProcessLookupError):
            process.kill()  # Abort ONLY the actual already-issued control CLI handle.
    if not owners.readers:
        if process.stdout is None or process.stderr is None:
            raise ValueError("Owned control CLI original pipes are unavailable")
        tasks = (
            asyncio.create_task(out.read(process.stdout)),
            asyncio.create_task(err.read(process.stderr)),
            asyncio.create_task(process.wait()),
        )
        owners.readers = tuple(cast(asyncio.Future[object], row) for row in tasks)
        for task in tasks:
            task.add_done_callback(_consume)
    await asyncio.shield(asyncio.gather(*owners.readers, return_exceptions=True))
