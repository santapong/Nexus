"""One owned process boundary returns raw output/host samples; no v2 result or effect authority."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from nexus.builder.contained_contracts import ParentObservation, ScopeExpectation
from nexus.builder.contained_diagnostics import error_kind
from nexus.builder.contained_discovery import ContainedDiscovery, DiscoveryUnavailableError
from nexus.builder.contained_evidence_types import (
    ExactContainer,
    ObservationDeadline,
    ObservedSample,
)
from nexus.builder.contained_observer import ContainmentObserver
from nexus.builder.contained_observer_io import OwnedObservationIO, _proc
from nexus.builder.contained_parent_diagnostics import failure_parent_attempt
from nexus.builder.contained_process_contracts import (
    ContainedRunCapture,
    PreparedContainedLaunch,
    ProcessRunBinding,
    ProcessSampling,
    assemble_capture,
    capture_limits,
    process_diagnostic,
    require_spawn_ready,
    runtime_membership,
)
from nexus.builder.contained_process_contracts import (
    StartedContainedProcess as StartedContainedProcess,
)
from nexus.builder.contained_query import clock_us
from nexus.builder.contained_spawn_window import SpawnWindow
from nexus.builder.process import ProcessCapture, engine_environment


class ProcessOwnershipUnresolvedError(ValueError):
    """A spawn may have happened, but its exact child could not be obtained/reaped in time."""

    def __init__(
        self,
        message: str,
        pending: asyncio.Task[asyncio.subprocess.Process] | None = None,
        process: asyncio.subprocess.Process | None = None,
    ) -> None:
        super().__init__(message)
        self.pending, self.process = pending, process  # Strong ownership, never a retry permit.


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


class CurrentParents(Protocol):
    """Root sealed services supply the actual current provider; no action callback."""

    async def observe(self, expected: ScopeExpectation) -> ParentObservation:
        """Read the exact current parent again."""
        ...


class SpawnWindowWatch(Protocol):
    """Root actual DB-clock producer and existing current source/lease watchdog."""

    async def before_spawn(self) -> SpawnWindow:
        """Current authority read, with monotonic anchor before its final SQL clock query."""
        ...

    async def check(self) -> None:
        """Continue actual source/lease checks during the one issued call."""
        ...


class ContainedProcess:
    """Every run creates its own observer and keeps one absolute end; replay is store-only."""

    def __init__(
        self,
        parents: CurrentParents,
        discovery: ContainedDiscovery | None = None,
        *,
        clock_us: Callable[[], int] = clock_us,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.parents = parents
        self.discovery = discovery if discovery is not None else ContainedDiscovery()
        self._clock, self._utc = clock_us, utc_now

    async def start(
        self,
        launch: PreparedContainedLaunch,
        binding: ProcessRunBinding,
        expectation: ScopeExpectation,
        watch: SpawnWindowWatch,
        deadline: ObservationDeadline | None = None,
    ) -> StartedContainedProcess:
        """Last awaited authority read, fresh parent, synchronous checks, immediate exact spawn."""
        launch = PreparedContainedLaunch.model_validate(launch.model_dump())
        if launch.binding != binding:
            raise ValueError("Contained launch uses another original issued binding")
        if deadline is None:
            raise ValueError("Contained start requires the original fixed operation end")
        process: asyncio.subprocess.Process | None = None
        environment = engine_environment()  # Resolve account/files before the final parent read.
        try:
            async with asyncio.timeout(self._remaining(deadline.end_us - 100_000)):
                window = await watch.before_spawn()
                if (
                    not isinstance(window, SpawnWindow)
                    or window.operation_end_us != deadline.end_us
                ):
                    raise ValueError("Contained original operation budget differs before spawn")
                parent = await self.parents.observe(expectation)
                require_spawn_ready(
                    launch,
                    binding,
                    parent,
                    window,
                    monotonic_now_us=self._clock(),
                    utc_now=self._utc(),
                )
                now = self._clock()  # Recheck after all descriptor validation/hashing CPU.
                if not parent.observed_end_us <= now < parent.deadline_us:
                    raise ValueError("Contained parent expired during descriptor validation")
                window.require_current(monotonic_now_us=now, utc_now=self._utc())
                # No awaited DB/engine/file IO between final check and this spawn primitive.
                process = await self._spawn(launch, deadline, environment, parent, window)
                ticks, path = await self._runtime_process(
                    process, min(deadline.end_us, parent.deadline_us)
                )
                membership = runtime_membership(path, parent)
                return StartedContainedProcess(process, parent, window, ticks, path, membership)
        except BaseException:
            if process is not None:
                await self._cancel_spawned(process, deadline)
            raise

    def _remaining(self, end: int) -> float:
        value = end - self._clock()
        if value <= 0:
            raise TimeoutError("Contained process shared end expired")
        return value / 1_000_000

    async def _runtime_process(
        self, process: asyncio.subprocess.Process, end: int
    ) -> tuple[int | None, str | None]:
        try:
            async with asyncio.timeout(self._remaining(end - 100_000)):
                return await asyncio.to_thread(_proc, process.pid)
        except (OSError, ValueError):
            return None, None  # Short-lived or inaccessible PID does not prove a live identity.

    async def _cancel_spawned(
        self, process: asyncio.subprocess.Process, deadline: ObservationDeadline
    ) -> None:
        # The owned child handle is preserved; no container/scope force cleanup is inferred.
        try:
            async with asyncio.timeout(self._remaining(deadline.end_us)):
                if process.returncode is None:
                    process.kill()  # Unreaped owned child handle; never a caller-supplied PID.
                await process.wait()
        except (OSError, TimeoutError):
            raise ProcessOwnershipUnresolvedError(
                "Contained runtime reaping remains unresolved", process=process
            ) from None

    async def _spawn(
        self,
        launch: PreparedContainedLaunch,
        deadline: ObservationDeadline,
        environment: dict[str, str],
        parent: ParentObservation,
        window: SpawnWindow,
    ) -> asyncio.subprocess.Process:
        async def issue() -> asyncio.subprocess.Process:
            # Scheduling another task can consume the final source/lease window.
            now = self._clock()
            if not parent.observed_end_us <= now < min(parent.deadline_us, deadline.end_us):
                raise ValueError("Contained parent or operation expired before scheduled spawn")
            window.require_current(monotonic_now_us=now, utc_now=self._utc())
            return await asyncio.create_subprocess_exec(
                *launch.argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
            )

        pending = asyncio.create_task(issue())
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            try:
                async with asyncio.timeout(self._remaining(deadline.end_us)):
                    process = await asyncio.shield(pending)
                    await self._cancel_spawned(process, deadline)
            except (OSError, TimeoutError, ProcessOwnershipUnresolvedError) as failure:
                pending.add_done_callback(_consume_spawn)
                raise ProcessOwnershipUnresolvedError(
                    "Contained spawn ownership is unresolved", pending=pending
                ) from failure
            raise

    # Keep this >50-line issued lifecycle together to bind failure, ownership and raw metadata.
    async def run(
        self,
        launch: PreparedContainedLaunch,
        binding: ProcessRunBinding,
        expectation: ScopeExpectation,
        watch: SpawnWindowWatch,
        deadline: ObservationDeadline,
        *,
        stdout_limit: int,
        stderr_limit: int,
    ) -> ContainedRunCapture:
        capture_limits(stdout_limit, stderr_limit)
        started_us = self._clock()
        started = await self.start(launch, binding, expectation, watch, deadline)
        assert started.process.stdout is not None and started.process.stderr is not None
        stdout_prefix, stderr_prefix = _Prefix(stdout_limit), _Prefix(stderr_limit)
        out = asyncio.create_task(stdout_prefix.read(started.process.stdout))
        err = asyncio.create_task(stderr_prefix.read(started.process.stderr))
        wait = asyncio.create_task(started.process.wait())
        observer = ContainmentObserver(OwnedObservationIO())  # NEW instance per issued job.
        state = ProcessSampling(out, err, wait)
        reason: str | None = None
        try:
            if started.runtime_membership != "observed_path":
                raise ValueError("Contained runtime parent path is unproven")
            async with asyncio.timeout(
                self._remaining(min(deadline.end_us, started.parent.deadline_us) - 100_000)
            ):
                await self._monitor(started, launch, expectation, watch, deadline, observer, state)
        except (OSError, ValueError, TimeoutError) as failure:
            reason = type(failure).__name__
            state.error_type = error_kind(failure)
            state.errno = failure.errno if isinstance(failure, OSError) else None
            if state.phase == "parent":
                state.parent_attempt = failure_parent_attempt(failure, expectation)
        finally:
            uncertain = await self._finish_runtime(started, out, err, wait, deadline)
        return _capture(
            started,
            deadline,
            state.sealed,
            state.samples,
            stdout_prefix,
            stderr_prefix,
            wait,
            max(0, (self._clock() - started_us) // 1000),
            reason,
            uncertain,
            self._clock,
            binding,
            state,
        )

    async def _monitor(
        self,
        started: StartedContainedProcess,
        launch: PreparedContainedLaunch,
        expectation: ScopeExpectation,
        watch: SpawnWindowWatch,
        deadline: ObservationDeadline,
        observer: ContainmentObserver,
        state: ProcessSampling,
    ) -> None:
        while started.process.returncode is None and not state.wait.done():
            if deadline.remaining_us(self._clock(), started.parent) <= 100_000:
                raise TimeoutError(
                    "Contained shared end reached; preserve infrastructure uncertainty"
                )
            if any(task.done() and task.exception() for task in (state.out, state.err)):
                raise ValueError("Contained raw process output overflow")
            state.phase = "watch"
            await watch.check()
            if state.sealed is None:
                try:
                    state.phase = "discovery"
                    container = await self.discovery.discover(
                        launch,
                        started.process.pid,
                        min(deadline.end_us, started.parent.deadline_us),
                        recorder=state.discovery,
                    )
                    state.sealed = container
                except DiscoveryUnavailableError:
                    await asyncio.wait((state.wait,), timeout=0.1)
                    continue  # Read-only name discovery; never repeat the issued process.
            state.phase = "parent"
            parent = await self.parents.observe(expectation)
            state.phase = "sample"
            row = await observer.sample(parent, state.sealed, deadline)
            state.samples.append(row)
            if row.status != "observed_contained" or len(state.samples) >= 12001:
                raise ValueError("Contained host sample remains incomplete")
            state.phase = "wait"
            await asyncio.wait((state.wait,), timeout=0.1)
        state.phase = "complete"

    async def _finish_runtime(
        self,
        started: StartedContainedProcess,
        out: asyncio.Task[bytes],
        err: asyncio.Task[bytes],
        wait: asyncio.Task[int],
        deadline: ObservationDeadline,
    ) -> bool:
        process = started.process
        uncertain = False
        try:
            remaining = deadline.remaining_us(self._clock(), started.parent)
            async with asyncio.timeout(remaining / 1_000_000):
                if process.returncode is None:
                    try:
                        current, _ = await asyncio.to_thread(_proc, process.pid)
                        if (
                            started.runtime_start_ticks is None
                            or current != started.runtime_start_ticks
                        ):
                            uncertain = True
                        else:
                            process.kill()  # Exact runtime; container cleanup stays Root-owned.
                    except (OSError, ValueError):
                        uncertain = True
                values = await asyncio.gather(out, err, wait, return_exceptions=True)
                uncertain = uncertain or any(isinstance(value, BaseException) for value in values)
        except TimeoutError:
            uncertain = True
            for task in (out, err, wait):
                if not task.done():
                    task.cancel()
            values = await asyncio.gather(out, err, wait, return_exceptions=True)
        return uncertain


def _consume_spawn(task: asyncio.Task[asyncio.subprocess.Process]) -> None:
    """Consume terminal failure; cancellation uncertainty never fabricates a reaped child."""
    if not task.cancelled():
        task.exception()


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
    result = assemble_capture(started, deadline, sealed, samples, capture, wait, reason, uncertain)
    result = result.model_copy(update={"parent_attempt": state.parent_attempt})
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
