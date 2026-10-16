"""One owned process boundary returns raw output/host samples; no v2 result or effect authority."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, cast

from nexus.builder.contained_contracts import ParentObservation, ScopeExpectation
from nexus.builder.contained_diagnostics import error_kind
from nexus.builder.contained_discovery import ContainedDiscovery, DiscoveryUnavailableError
from nexus.builder.contained_evidence_types import (
    ObservationDeadline,
)
from nexus.builder.contained_issued_context import OwnedStart, open_owned_start
from nexus.builder.contained_observer import ContainmentObserver
from nexus.builder.contained_observer_io import OwnedObservationIO, _proc
from nexus.builder.contained_owned_stop import ContainedOwnedStop
from nexus.builder.contained_owned_stop_lifecycle import finish_owned_cleanup
from nexus.builder.contained_parent_diagnostics import failure_parent_attempt
from nexus.builder.contained_process_capture import _capture, _Prefix
from nexus.builder.contained_process_contracts import (
    ContainedRunCapture,
    PreparedContainedLaunch,
    ProcessRunBinding,
    ProcessSampling,
    capture_limits,
    require_spawn_ready,
    runtime_membership,
)
from nexus.builder.contained_process_contracts import (
    StartedContainedProcess as StartedContainedProcess,
)
from nexus.builder.contained_query import clock_us
from nexus.builder.contained_spawn_window import SpawnWindow
from nexus.builder.process import engine_environment
from nexus.builder.systemd_scope_provider import SystemdScopeProvider


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
        self.stopper = ContainedOwnedStop(clock=clock_us)
        self.cleanup_owners: set[asyncio.Future[object]] = set()

    # Keep the >50-line preissue ownership/last-window/spawn transaction and failure close together.
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
        owner: OwnedStart | None = None
        environment = engine_environment()  # Resolve account/files before the final parent read.
        try:
            async with asyncio.timeout(self._remaining(deadline.end_us - 100_000)):
                if isinstance(self.parents, SystemdScopeProvider):
                    owner = await open_owned_start(binding, expectation, deadline.end_us)
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
                if owner is not None:
                    owner.bind_spawn(process, parent, ticks)
                return StartedContainedProcess(
                    process, parent, window, ticks, path, membership, owner
                )
        except BaseException:
            try:
                if process is not None:
                    await self._cancel_spawned(process, deadline)
            finally:
                if owner is not None:
                    owner.close()
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
        stopper = self.stopper  # Retain the original configured stop across every awaited step.
        started = await self.start(launch, binding, expectation, watch, deadline)
        assert started.process.stdout is not None and started.process.stderr is not None
        stdout_prefix, stderr_prefix = _Prefix(stdout_limit), _Prefix(stderr_limit)
        out = asyncio.create_task(stdout_prefix.read(started.process.stdout))
        err = asyncio.create_task(stderr_prefix.read(started.process.stderr))
        wait = asyncio.create_task(started.process.wait())
        observer = ContainmentObserver(OwnedObservationIO())  # NEW instance per issued job.
        state = ProcessSampling(out, err, wait)
        reason: str | None = None
        first: BaseException | None = None
        try:
            if started.runtime_membership != "observed_path":
                raise ValueError("Contained runtime parent path is unproven")
            async with asyncio.timeout(
                self._remaining(min(deadline.end_us, started.parent.deadline_us) - 100_000)
            ):
                await self._monitor(started, launch, expectation, watch, deadline, observer, state)
        except BaseException as failure:
            first = failure
            if not isinstance(failure, (OSError, ValueError, TimeoutError)):
                raise
            reason = type(failure).__name__
            state.error_type = error_kind(failure)
            state.errno = failure.errno if isinstance(failure, OSError) else None
            if state.phase == "parent":
                state.parent_attempt = failure_parent_attempt(failure, expectation)
        finally:
            finished = await finish_owned_cleanup(
                stopper,
                started,
                binding,
                deadline,
                state,
                first,
                lambda: self._finish_runtime(started, out, err, wait, deadline),
                self.cleanup_owners,
                self._clock,
            )
            uncertain, state.issued_cleanup = finished.unresolved, finished.issued_cleanup
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

    # Keep discovery-seal consumption and post-only sampling in one >50-line state boundary.
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
                    if started.owned_start is not None:
                        if type(self.discovery) is not ContainedDiscovery:
                            raise ValueError("Post-seal context requires concrete fixed discovery")
                        state.issued_context = started.owned_start.seal(
                            self.discovery.take_owned_seal(container)
                        )
                except DiscoveryUnavailableError:
                    await asyncio.wait((state.wait,), timeout=0.1)
                    continue  # Read-only name discovery; never repeat the issued process.
            state.phase = "parent"
            if state.issued_context is not None:
                if not isinstance(self.parents, SystemdScopeProvider):
                    raise ValueError("Post-seal parent requires concrete configured provider")
                parent = await self.parents.observe_after_owned_spawn(
                    expectation, state.issued_context
                )
                state.issued_identity = parent.issued_identity
            else:
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
            async with asyncio.timeout(max(0, remaining - 100_000) / 1_000_000):
                if process.returncode is None:
                    try:

                        def read(pid: int) -> tuple[int, str]:
                            self._remaining(deadline.end_us - 100_000)
                            return _proc(pid)

                        probe = asyncio.create_task(asyncio.to_thread(read, process.pid))
                        retained = cast(asyncio.Future[object], probe)
                        self.cleanup_owners.add(retained)
                        probe.add_done_callback(self.cleanup_owners.discard)
                        probe.add_done_callback(_consume_owner)
                        current, _ = await asyncio.shield(probe)
                        if (
                            started.runtime_start_ticks is None
                            or current != started.runtime_start_ticks
                        ):
                            uncertain = True
                        else:
                            process.kill()  # Exact runtime; container cleanup stays Root-owned.
                    except (OSError, ValueError):
                        uncertain = True
                values = await asyncio.shield(
                    asyncio.gather(out, err, wait, return_exceptions=True)
                )
                uncertain = uncertain or any(isinstance(value, BaseException) for value in values)
        except TimeoutError:
            uncertain = True
            # Keep actual drains/wait and the shielded proc worker owned. A cancelled
            # wrapper would not prove thread completion or reap the original child.
        return uncertain


def _consume_spawn(task: asyncio.Task[asyncio.subprocess.Process]) -> None:
    """Consume terminal failure; cancellation uncertainty never fabricates a reaped child."""
    if not task.cancelled():
        task.exception()


def _consume_owner[T](task: asyncio.Future[T]) -> None:
    if not task.cancelled():
        task.exception()
