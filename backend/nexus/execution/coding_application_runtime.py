"""Retain both actual L/C owner/native leaves, then public C SDK teardown and engine disposal."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from nexus.execution import coding_worker, planning_worker
from nexus.execution.coding_application import CodingApplication
from nexus.execution.planning_application_runtime import (
    PlanningWorkerRuntime,
    _shield_retirement,
    capture_planning_worker_runtime,
)


async def drain_coding_application(
    value: CodingApplication, *, destroy: Callable[[], Awaitable[None]] | None = None
) -> None:
    """Capture actual readers before yielding so facade replacement cannot detach ownership."""
    planning = value.planning.lifecycle
    coding = value.lifecycle
    reads = value.reads
    costs = value.planning.cycle_costs.reads if value.planning.cycle_costs is not None else None
    review = value.planning.management.action_reviews
    planning.request_stop()
    coding.request_stop()
    while (
        planning.pending_owners()
        or coding.pending_owners()
        or reads.pending_owners()
        or (costs is not None and costs.pending_owners())
        or (review is not None and review.pending_owners())
        or any(op.running for op in value.planning.runtime._operations.values())
        or any(op.running for op in value.services._operations.values())
    ):
        await asyncio.sleep(0.05)
    if destroy is not None:
        await destroy()


async def retire_coding_application(
    value: CodingApplication,
    *,
    destroy: Callable[[], Awaitable[None]] | None,
    dispose: Callable[[], Awaitable[None]],
) -> None:
    """Repeated caller cancellation retains the actual complete retirement task."""

    async def retirement() -> None:
        await drain_coding_application(value, destroy=destroy)
        await dispose()

    await _shield_retirement(asyncio.create_task(retirement()))


async def start_coding_application_worker(
    value: CodingApplication, system_database_url: str
) -> PlanningWorkerRuntime:
    """Dedicated process only; the I launcher is the sole one-shot queue selector."""
    value.require_composition()
    value.services.require_accepting()
    if planning_worker._services is not None or coding_worker._services is not None:
        raise ValueError("Coding needs its separate previously unconfigured worker process")
    runtime = await capture_planning_worker_runtime(value.planning)
    coding_worker.configure_coding_worker(value.services, system_database_url)
    try:
        await coding_worker.launch_coding_worker()
    except BaseException as first:
        task = asyncio.create_task(drain_coding_application(value, destroy=runtime.destroy))
        try:
            await _shield_retirement(task)
        except BaseException as secondary:
            first.__dict__["_nexus_coding_secondary"] = type(secondary).__name__
        raise first
    return runtime
