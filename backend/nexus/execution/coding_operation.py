"""Original C operation/leaf ownership across cancellation; no renewed execution window."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from nexus.builder.contained_query import clock_us
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.management.coding_consumer import RegisteredCodingConsumer
from nexus.company.management.coding_prepared_store import CodingPreparedStore
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.coding_services import ENTRY_SECONDS, CodingServices
from nexus.execution.runtime_contracts import ExecutionLease, ExecutionSnapshot
from nexus.execution.runtime_support import db_now


@dataclass(frozen=True, slots=True)
class CodingOperationRead[T]:
    """Internal original operation cutoff; never a public authority/monotonic field."""

    value: T
    read_end_us: int


def current(end_us: int) -> None:
    """Check only the original monotonic operation end."""
    if type(end_us) is not int or not 0 < clock_us() < end_us:
        raise TimeoutError("Original coding operation expired")


async def clock_now(services: CodingServices) -> datetime:
    """Read the actual database clock; never renew authority from caller wall time."""
    async with services.factory() as session:
        return await db_now(session)


async def wait_resources(owners: tuple[asyncio.Future[object], ...], end: float) -> None:
    """Wait for real owners without cancelling them when the waiting caller stops."""
    if owners:
        await asyncio.wait(owners, timeout=max(0, end - asyncio.get_running_loop().time()))


class CodingOperation:
    """Actual lease/tasks/consumer remain reachable after denied or interrupted delivery."""

    running: bool

    def __init__(self, services: CodingServices, key: str, end_us: int) -> None:
        services.require_accepting()
        current(end_us)
        if services.pending_owners() or any(
            value.running for value in services._operations.values()
        ):
            raise ValueError("Coding retains an unfinished original operation")
        driver = asyncio.current_task()
        if driver is None:
            raise ValueError("Coding needs the actual orchestration task")
        self.services, self.key, self.driver = services, key, driver
        self.end = min(end_us, clock_us() + ENTRY_SECONDS * 1_000_000)
        self.owners: list[asyncio.Task[object]] = []
        self.credential: AuthenticatedWorkerIdentity | None = None
        self.lease_task: asyncio.Task[ExecutionLease] | None = None
        self.waiting_task: asyncio.Task[ExecutionSnapshot] | None = None
        self.lease: ExecutionLease | None = None
        self.consumer: RegisteredCodingConsumer | None = None
        self._store: CodingPreparedStore | None = None
        self.first: BaseException | None = None
        self.released, self.running, self._stop_sent = False, True, False
        services._operations[key] = self

    @property
    def prepared(self) -> CodingPreparedStore:
        if self._store is None:
            self.require_admission()
            self._store = self.services.create_prepared()
        return self._store

    def request_stop(self) -> None:
        if self._store is not None:
            self._store.request_stop()
        if self.consumer is not None:
            self.consumer.request_stop()
        if not self._stop_sent and self.running and not self.driver.done():
            self._stop_sent = True
            self.driver.get_loop().call_soon_threadsafe(self.driver.cancel, "Coding stopping")

    def require_current(self) -> None:
        current(self.end)
        self.services.require_composition()

    def require_admission(self) -> None:
        self.require_current()
        self.services.require_accepting()
        if self.first is not None or self._stop_sent:
            raise ValueError("Original coding caller stopped admission")

    def shorten(self, now: datetime, before_us: int, deadlines: tuple[datetime, ...]) -> None:
        """Carry the actual clock's original windows through transaction exit and later IO."""
        self.end = min(
            (
                self.end,
                *(before_us + (value - now) // timedelta(microseconds=1) for value in deadlines),
            )
        )
        self.require_current()

    async def call[T](self, value: Awaitable[T], *, end_us: int | None = None) -> T:
        limit = min(self.end, end_us if end_us is not None else self.end)
        try:
            current(limit)
            self.services.require_composition()
        except BaseException:
            if inspect.iscoroutine(value):
                value.close()
            elif isinstance(value, asyncio.Task):
                self.owners.append(cast(asyncio.Task[object], value))
            raise
        task = asyncio.ensure_future(value)
        self.owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            async with asyncio.timeout(max(0, limit - clock_us()) / 1_000_000):
                result = await asyncio.shield(task)
        except BaseException as first:
            self.first = self.first or first
            if self._store is not None:
                # Its admitted leaf stays owned; the rest of the private pipeline stops.
                self._store.request_stop()
            if self.consumer is not None:
                self.consumer.request_stop()
            raise
        current(limit)
        self.services.require_composition()
        return result

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        return tuple(
            dict.fromkeys(
                (
                    *(task for task in self.owners if not task.done() or task.cancelled()),
                    *(self.consumer.pending_owners() if self.consumer is not None else ()),
                    *(self._store.pending_owners() if self._store is not None else ()),
                    *self.services.evidence.pending_owners(),
                    *self.services.prepared_blobs.pending_owners(),
                    *cast(
                        ProtectedBlobStore, self.services.contexts._retriever.blobs
                    ).pending_owners(),
                )
            )
        )

    async def retire(self) -> None:
        """Resource-only completion; no renewed lease, later candidate or expired-end SQL."""
        while self.pending_owners() and clock_us() < self.end:
            if any(task.cancelled() for task in self.pending_owners()):
                return  # A cancelled wrapper cannot prove its underlying resource settled.
            try:
                await wait_resources(
                    self.pending_owners(),
                    asyncio.get_running_loop().time() + max(0, self.end - clock_us()) / 1_000_000,
                )
            except asyncio.CancelledError as first:
                self.first = self.first or first
        if self.pending_owners():
            return
        if (
            self.lease_task is not None
            and self.lease_task.done()
            and not self.lease_task.cancelled()
            and self.lease_task.exception() is None
        ):
            self.lease = self.lease_task.result()  # Actual resource handle, never new execution.
        if (
            self.waiting_task is not None
            and self.waiting_task.done()
            and not self.waiting_task.cancelled()
            and self.waiting_task.exception() is None
        ):
            self.released = self.waiting_task.result().worker_id is None
        if self.lease is not None and self.credential is not None and not self.released:
            self.require_current()
            now = await self.call(clock_now(self.services))
            self.credential.require_time(now)
            if self.lease.expires_at <= now:
                raise ValueError("Original coding lease expired before resource release")
            await self.call(
                self.services.execution.release(
                    self.lease,
                    self.credential.identity,
                    blocked=self.first is not None,
                )
            )
            self.released = True

    def finish(self) -> None:
        self.running = False
        if not self.pending_owners():
            self.services._operations.pop(self.key, None)
        if self.first is not None:
            self.first.__dict__["_nexus_coding_pending"] = self.pending_owners()
            self.first.__dict__["_nexus_coding_operation"] = self
