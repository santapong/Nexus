"""One shielded interruption cleanup owns stop, original CLI settlement and descriptor close."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, cast

from nexus.builder.contained_evidence_types import ObservationDeadline
from nexus.builder.contained_issued_context import OwnedStart
from nexus.builder.contained_owned_stop import ContainedOwnedStop
from nexus.builder.contained_owned_stop_io import StopIOUnresolvedError
from nexus.builder.contained_process_contracts import (
    ProcessRunBinding,
    ProcessSampling,
    StartedContainedProcess,
)


@dataclass
class CleanupReason:
    first: BaseException | None
    changed: asyncio.Future[None]


@dataclass(frozen=True)
class OwnedCleanupResult:
    unresolved: bool
    issued_cleanup: Literal["closed", "deferred"] | None
    first: BaseException | None
    secondary: tuple[BaseException, ...]
    retained: tuple[asyncio.Future[object], ...]
    io_failure: StopIOUnresolvedError | None
    owner: OwnedStart | None
    process: asyncio.subprocess.Process

    def resources_settled(self) -> bool:
        """Actual handle/FD completion only; frozen semantic UNKNOWN is unchanged."""
        if self.process.returncode is None or any(
            not row.done() or row.cancelled() for row in self.retained
        ):
            return False
        if self.io_failure is not None and not self.io_failure.owners.settled():
            return False
        owner = self.owner
        return owner is None or (
            owner.process is self.process
            and owner._closed
            and owner._root_fd is None
            and owner._leaf_fd is None
            and all(row.done() and not row.cancelled() for row in owner._pending)
        )


async def finish_owned_cleanup(
    stopper: ContainedOwnedStop,
    started: StartedContainedProcess,
    binding: ProcessRunBinding,
    deadline: ObservationDeadline,
    state: ProcessSampling,
    first: BaseException | None,
    finish_runtime: Callable[[], Awaitable[bool]],
    owners: set[asyncio.Future[object]],
    clock: Callable[[], int],
) -> OwnedCleanupResult:
    reason = CleanupReason(first, asyncio.get_running_loop().create_future())
    task = asyncio.create_task(
        _finish(stopper, started, binding, deadline, state, reason, finish_runtime, owners)
    )
    retained = cast(asyncio.Future[object], task)
    owners.add(retained)  # Ownership is visible before any fallible deadline mark/await.
    task.add_done_callback(lambda done: _finished(done, owners))
    try:
        remaining = min(deadline.end_us, started.parent.deadline_us) - clock()
        if remaining <= 0:
            raise TimeoutError("Owned cleanup original end expired")
        async with asyncio.timeout(remaining / 1_000_000):
            return await asyncio.shield(task)
    except BaseException as failure:
        reason.first = reason.first or failure
        if not reason.changed.done():
            reason.changed.set_result(None)
        reason.first.__dict__["_nexus_owned_cleanup_task"] = task
        reason.first.__dict__["_nexus_owned_cleanup_owners"] = owners
        raise reason.first from None  # Keep first cause, not a repeated cancellation/stop failure.


async def _finish(
    stopper: ContainedOwnedStop,
    started: StartedContainedProcess,
    binding: ProcessRunBinding,
    deadline: ObservationDeadline,
    state: ProcessSampling,
    reason: CleanupReason,
    finish_runtime: Callable[[], Awaitable[bool]],
    owners: set[asyncio.Future[object]],
) -> OwnedCleanupResult:
    secondary: list[BaseException] = []
    io_failure: StopIOUnresolvedError | None = None
    attempted = False

    async def stop() -> None:
        nonlocal attempted, io_failure
        if attempted or reason.first is None:
            return
        attempted = True
        if state.issued_context is None or started.owned_start is None:
            return  # Original unsealed branch stays unproven; no ID/name guessing.
        try:
            await stopper.stop(state.issued_context, started, binding, deadline)
        except BaseException as error:
            secondary.append(error)
            candidate = (
                error
                if isinstance(error, StopIOUnresolvedError)
                else error.__dict__.get("_nexus_owned_stop_io")
            )
            if isinstance(candidate, StopIOUnresolvedError):
                io_failure = candidate
            reason.first.__dict__["_nexus_owned_stop_error"] = error

    await stop()
    drain = asyncio.ensure_future(finish_runtime())
    owners.add(cast(asyncio.Future[object], drain))
    drain.add_done_callback(lambda done: _drain_finished(done, owners))
    try:
        if reason.first is None:
            # A normal drain must not hide a timely first cancellation until its end.
            # The signal is only a Future; the actual drain task is never cancelled.
            await asyncio.wait((drain, reason.changed), return_when=asyncio.FIRST_COMPLETED)
        await stop()
        unresolved = await asyncio.shield(drain)
    except BaseException as failure:
        reason.first = reason.first or failure
        secondary.append(failure)
        unresolved = True
    # Cancellation arriving during a normal terminal CLI drain still precedes context close.
    await stop()
    tasks: tuple[asyncio.Future[object], ...] = tuple(
        cast(asyncio.Future[object], row) for row in (state.out, state.err, state.wait)
    )
    tasks += tuple(row for row in owners if row is not asyncio.current_task())
    if io_failure is not None:
        tasks += (cast(asyncio.Future[object], io_failure.owners.pending),)
        tasks += io_failure.owners.readers
        if io_failure.owners.retirement is not None:
            retirement = cast(asyncio.Future[object], io_failure.owners.retirement)
            owners.add(retirement)
            tasks += (retirement,)
    owner = started.owned_start
    if owner is not None:
        tasks += tuple(owner._pending)

    def can_close() -> bool:
        return (
            all(row.done() and not row.cancelled() for row in tasks)
            and started.process.returncode is not None
            and (io_failure is None or io_failure.owners.settled())
        )

    descriptor_closed = False

    def close_when_settled(done: asyncio.Future[object] | None = None) -> None:
        nonlocal descriptor_closed
        if owner is not None and not descriptor_closed and can_close():
            try:
                descriptor_closed = (
                    owner.close()
                )  # Descriptor release only; no late engine command or adoption.
            except BaseException as error:
                if reason.first is not None:
                    reason.first.__dict__["_nexus_owned_close_error"] = error

    closed: Literal["closed", "deferred"] | None = None
    if owner is not None:
        if can_close():
            try:
                closed = "closed" if owner.close() else "deferred"
            except BaseException as error:
                reason.first = reason.first or error
                secondary.append(error)
                closed = "deferred"
        else:
            closed = "deferred"
            for row in tasks:
                row.add_done_callback(close_when_settled)
    return OwnedCleanupResult(
        unresolved or bool(secondary) or closed == "deferred",
        closed,
        reason.first,
        tuple(secondary),
        tasks,
        io_failure,
        owner,
        started.process,
    )


def _finished(done: asyncio.Task[OwnedCleanupResult], owners: set[asyncio.Future[object]]) -> None:
    if not done.cancelled():
        error = done.exception()
        if error is None and not done.result().unresolved:
            owners.discard(cast(asyncio.Future[object], done))


def _drain_finished(done: asyncio.Future[bool], owners: set[asyncio.Future[object]]) -> None:
    if not done.cancelled():
        done.exception()
        owners.discard(cast(asyncio.Future[object], done))
