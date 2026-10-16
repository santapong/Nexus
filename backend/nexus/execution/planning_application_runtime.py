"""Explicit fixed-queue startup and retirement of the actual shared planning resources."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial

from dbos import DBOS

from nexus.execution.planning_application import PlanningApplication
from nexus.execution.planning_worker import configure_planning_worker, launch_planning_worker


@dataclass(frozen=True, slots=True)
class PlanningWorkerRuntime:
    """Actual prelaunch host handles; the SDK's adopted pool is never the teardown owner."""

    loop: asyncio.AbstractEventLoop
    executor: ThreadPoolExecutor
    _retirement: asyncio.Future[None] | None = field(default=None, init=False, repr=False)

    def _current(self) -> None:
        if (
            asyncio.get_running_loop() is not self.loop
            or not isinstance(self.executor, ThreadPoolExecutor)
            or getattr(self.executor, "_shutdown", True) is not False
        ):
            raise ValueError("Original planning host loop/executor is unavailable")

    def pending_owners(self) -> tuple[asyncio.Future[None], ...]:
        """The actual teardown future remains reachable across caller cancellation."""
        value = self._retirement
        return (value,) if value is not None and (not value.done() or value.cancelled()) else ()

    async def destroy(self) -> None:
        """Use public DBOS teardown on the retained host; preserve its original ownership."""
        self._current()
        if self._retirement is None:
            object.__setattr__(
                self,
                "_retirement",
                self.loop.run_in_executor(
                    self.executor,
                    partial(DBOS.destroy, workflow_completion_timeout_sec=1),
                ),
            )
        assert self._retirement is not None
        try:
            await _shield_retirement(self._retirement)
        finally:
            self.loop.set_default_executor(self.executor)


async def capture_planning_worker_runtime(services: PlanningApplication) -> PlanningWorkerRuntime:
    """Observe the actual live host pool before any SDK launch/adoption, never guess a handle."""
    services.runtime.require_accepting()
    # Public asyncio initializes its own host executor before the SDK can replace
    # it. CPython3.12 handle/_shutdown observation follows the qualified host pattern.
    loop = asyncio.get_running_loop()
    executor = getattr(loop, "_default_executor", None)
    if executor is not None and (
        not isinstance(executor, ThreadPoolExecutor)
        or getattr(executor, "_shutdown", True) is not False
    ):
        raise ValueError("Original planning host loop/executor is unavailable")
    if executor is None:
        await asyncio.to_thread(lambda: None)
        executor = getattr(loop, "_default_executor", None)
    if not isinstance(executor, ThreadPoolExecutor):
        raise ValueError("Original planning host loop/executor is unavailable")
    value = PlanningWorkerRuntime(loop, executor)
    value._current()
    return value


async def drain_planning_application(
    services: PlanningApplication,
    *,
    destroy: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Stop admission, retain actual leaves and original clocks, then retire the runtime."""
    # Retain the actual reader before yielding; later facade replacement cannot
    # remove resources already owned by this application retirement.
    costs = services.cycle_costs.reads if services.cycle_costs is not None else None
    services.lifecycle.request_stop()
    while (
        services.lifecycle.pending_owners()
        or any(operation.running for operation in tuple(services.runtime._operations.values()))
        or (costs is not None and costs.pending_owners())
    ):
        # A cancelled wrapper remains pending: cancellation alone cannot establish
        # completion of the SDK/native/file resource hidden behind that wrapper.
        await asyncio.sleep(0.05)
    if destroy is not None:
        await destroy()


async def _shield_retirement(task: asyncio.Future[None]) -> None:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    task.result()


async def retire_planning_application(
    services: PlanningApplication,
    *,
    destroy: Callable[[], Awaitable[None]] | None,
    dispose: Callable[[], Awaitable[None]],
) -> None:
    """Caller cancellation cannot detach the actual runtime/engine retirement task."""

    async def retirement() -> None:
        await drain_planning_application(services, destroy=destroy)
        await dispose()

    await _shield_retirement(asyncio.create_task(retirement()))


async def start_planning_application_worker(
    services: PlanningApplication,
    system_database_url: str,
) -> PlanningWorkerRuntime:
    """Only the fixed planning queue; no migration, bootstrap, key lookup or provider call."""
    services.runtime.require_accepting()
    runtime = await capture_planning_worker_runtime(services)
    configure_planning_worker(services.runtime, system_database_url)
    try:
        await launch_planning_worker()
    except BaseException as first:
        # Configuration succeeded, so this startup owns teardown even if launch or
        # queue registration failed after partially starting the actual runtime.
        task = asyncio.create_task(drain_planning_application(services, destroy=runtime.destroy))
        try:
            await _shield_retirement(task)
        except BaseException as secondary:
            first.__dict__["_nexus_planning_secondary"] = type(secondary).__name__
        raise first
    return runtime
