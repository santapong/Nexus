"""Fence the selected HTTP transport before committing a new request handoff.

Stop and handoff commitment are ordered by the same lock. The underlying async
transport may start after that lock is released, so a committed request is
already issued/unknown and may finish later even if another thread then stops it.
"""

from __future__ import annotations

import time
from _thread import LockType
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import httpx2

from nexus.core.llm.company_adapter_contracts import ServerEndpoint


@dataclass
class TransportGuard:
    """Original monotonic end and owning operation's stop latch."""

    stopped: Callable[[], bool]
    end_us: int
    lock: LockType
    delegated: bool = False


_current: ContextVar[TransportGuard | None] = ContextVar("company_transport_guard", default=None)


@contextmanager
def transport_guard(stopped: Callable[[], bool], end_us: int, lock: LockType) -> Iterator[None]:
    """Bind the original operation boundary only to the current task context."""
    token = _current.set(TransportGuard(stopped, end_us, lock))
    try:
        yield
    finally:
        _current.reset(token)


class GuardedTransport(httpx2.AsyncBaseTransport):
    """Wrap a selected transport without taking over its lifecycle."""

    def __init__(self, delegate: httpx2.AsyncBaseTransport, guard: TransportGuard) -> None:
        self.delegate = delegate
        self.guard = guard

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        with self.guard.lock:
            if (
                self.guard.delegated
                or self.guard.stopped()
                or time.monotonic_ns() // 1000 >= self.guard.end_us
            ):
                raise httpx2.RequestError(
                    "Model transport delegation is no longer current", request=request
                )
            self.guard.delegated = True
            handoff = self.delegate.handle_async_request(request)
        return await handoff


class GuardedAsyncClient(httpx2.AsyncClient):
    """Keep HTTPX's normal transport, proxy selection and lifecycle intact."""

    def __init__(
        self,
        endpoint: ServerEndpoint,
        observe: Callable[[httpx2.Response], Awaitable[None]],
    ) -> None:
        guard = _current.get()
        if guard is None:
            raise ValueError("Model transport requires an original operation guard")
        self._company_guard = guard
        super().__init__(
            transport=endpoint.transport,
            timeout=endpoint.timeout_seconds,
            event_hooks={"response": [observe]},
        )

    def _transport_for_url(self, url: httpx2.URL) -> httpx2.AsyncBaseTransport:
        # HTTPX's pinned send path resolves this for each hop, including redirects.
        return GuardedTransport(super()._transport_for_url(url), self._company_guard)
