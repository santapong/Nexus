"""Offline diagnostic: actual pinned SDK and fake-key MockTransport.

The first case is a red contract test on unchanged source if transport delegation
after a timeout is prohibited. An Authorizer fixture does not prove a real ledger.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock
from types import TracebackType
from typing import Self, cast

import httpx2
import pytest

from nexus.core.llm.company_adapter_contracts import (
    CompanyModelRequest,
    CompanyModelResult,
    ServerEndpoint,
)
from nexus.core.llm.company_adapters import CompanyModelAdapters
from nexus.core.llm.company_pricing import CostQuote
from nexus.core.llm.company_transport import (
    GuardedAsyncClient,
    GuardedTransport,
    TransportGuard,
    transport_guard,
)
from nexus.core.llm.qualification_contracts import (
    LEGACY_SDK_DISTRIBUTIONS,
    LEGACY_SDK_MODULES,
    SdkPins,
    _sdk_snapshot,
)
from nexus.harness.qualification_client import QualificationClient
from nexus.tests.unit import test_company_provider_conformance as fixture
from nexus.tests.unit.test_qualification_client import prepared


class ObservedMockTransport(httpx2.MockTransport):
    """Record entry to the actual injected transport separately from its handler."""

    def __init__(
        self,
        handler: Callable[[httpx2.Request], httpx2.Response]
        | Callable[[httpx2.Request], Coroutine[None, None, httpx2.Response]],
        events: list[str],
    ) -> None:
        super().__init__(handler)
        self.events = events

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.events.append("transport_entry")
        return await super().handle_async_request(request)


def model_with_timeout(
    provider: str,
    transport: httpx2.MockTransport,
    authority: fixture.Authorizer | None = None,
) -> CompanyModelAdapters:
    model = fixture.adapter(provider, transport, authority)
    resolver = cast(fixture.EndpointResolver, model._resolver)
    resolver.endpoint = replace(resolver.endpoint, timeout_seconds=1)
    return model


async def timed_out_with_owner(
    model: CompanyModelAdapters, task: asyncio.Task[CompanyModelResult]
) -> tuple[asyncio.Task[object], ...]:
    result = await asyncio.wait_for(task, 15)
    assert result.status == "failed"
    assert result.billing == "unknown"
    assert result.error_code == "sdk_resources_unresolved"
    owners = model.pending_owners()
    assert len(owners) == 1 and not owners[0].done()
    return owners


async def retire(owners: tuple[asyncio.Task[object], ...]) -> None:
    if owners:
        done, pending = await asyncio.wait(owners, timeout=15)
        assert not pending, "synthetic SDK owner did not retire"
        for task in done:
            task.result()


async def finish(
    task: asyncio.Task[CompanyModelResult],
    model: CompanyModelAdapters,
    release: asyncio.Event,
    owners: tuple[asyncio.Task[object], ...],
) -> None:
    release.set()
    if not task.done():
        _, pending = await asyncio.wait({task}, timeout=15)
        assert not pending, "synthetic caller did not retire"
    if not task.cancelled():
        task.exception()  # Retrieve any exception without changing its outcome.
    await retire(owners or model.pending_owners())


@pytest.mark.parametrize("provider", ["openai", "google"])
async def test_no_transport_delegation_after_timeout(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    entered, release = asyncio.Event(), asyncio.Event()
    original_send = httpx2.AsyncClient._send_single_request

    async def gate_before_delegation(
        client: httpx2.AsyncClient, request: httpx2.Request
    ) -> httpx2.Response:
        events.append("sdk_send_entered")
        entered.set()
        await release.wait()
        events.append("send_gate_released")
        return await original_send(client, request)

    def handler(request: httpx2.Request) -> httpx2.Response:
        events.append("mock_post")
        return httpx2.Response(200, json=fixture.response(provider))

    monkeypatch.setattr(httpx2.AsyncClient, "_send_single_request", gate_before_delegation)
    authority = fixture.Authorizer()
    model = model_with_timeout(provider, ObservedMockTransport(handler, events), authority)
    task = asyncio.create_task(model.request_once(fixture.request(), now=fixture.NOW))
    owners: tuple[asyncio.Task[object], ...] = ()
    try:
        await asyncio.wait_for(entered.wait(), 15)
        owners = await timed_out_with_owner(model, task)
        events.append("caller_returned_unknown")
        assert "transport_entry" not in events and "mock_post" not in events
    finally:
        await finish(task, model, release, owners)
    # Expected to FAIL against the unchanged implementation if the gap exists.
    assert "transport_entry" not in events, events
    assert "mock_post" not in events, events
    assert authority.claims == 1
    assert model.pending_owners() == ()


@pytest.mark.parametrize("provider", ["openai", "google"])
async def test_already_delegated_transport_remains_owned(provider: str) -> None:
    events: list[str] = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(request: httpx2.Request) -> httpx2.Response:
        entered.set()
        await release.wait()
        events.append("mock_post")
        return httpx2.Response(200, json=fixture.response(provider))

    model = model_with_timeout(provider, ObservedMockTransport(handler, events))
    task = asyncio.create_task(model.request_once(fixture.request(), now=fixture.NOW))
    owners: tuple[asyncio.Task[object], ...] = ()
    try:
        await asyncio.wait_for(entered.wait(), 15)
        assert events == ["transport_entry"]
        owners = await timed_out_with_owner(model, task)
        events.append("caller_returned_unknown")
    finally:
        await finish(task, model, release, owners)
    assert events == ["transport_entry", "caller_returned_unknown", "mock_post"]
    assert model.pending_owners() == ()


@pytest.mark.parametrize("provider", ["openai", "google"])
async def test_pre_sdk_gate_stops_without_delegation(provider: str) -> None:
    events: list[str] = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def before(
        request: CompanyModelRequest, quote: CostQuote, eligibility_sha256: str | None
    ) -> datetime:
        entered.set()
        await release.wait()
        return datetime.now(UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
        events.append("mock_post")
        return httpx2.Response(200, json=fixture.response(provider))

    model = model_with_timeout(provider, ObservedMockTransport(handler, events))
    model._before_sdk = before
    task = asyncio.create_task(model.request_once(fixture.request(), now=fixture.NOW))
    owners: tuple[asyncio.Task[object], ...] = ()
    try:
        await asyncio.wait_for(entered.wait(), 15)
        owners = await timed_out_with_owner(model, task)
    finally:
        await finish(task, model, release, owners)
    assert events == []
    assert model.pending_owners() == ()


async def test_original_end_fences_delegation_even_without_stop_latch() -> None:
    events: list[str] = []
    transport = ObservedMockTransport(lambda req: httpx2.Response(200), events)
    guard = GuardedTransport(
        transport, TransportGuard(lambda: False, time.monotonic_ns() // 1000 - 1, Lock())
    )
    with pytest.raises(httpx2.RequestError):
        await guard.handle_async_request(httpx2.Request("POST", "https://offline.invalid"))
    assert events == []


async def test_expired_end_fences_when_event_loop_is_blocked_before_stop_callback() -> None:
    events: list[str] = []
    stopped = Event()
    end = time.monotonic_ns() // 1000 + 20_000
    guard = GuardedTransport(
        ObservedMockTransport(lambda req: httpx2.Response(200), events),
        TransportGuard(stopped.is_set, end, Lock()),
    )
    callback = asyncio.get_running_loop().call_later(0.02, stopped.set)
    try:
        time.sleep(0.05)  # Simulate synchronous SDK work preventing timeout delivery.
        assert not stopped.is_set()
        with pytest.raises(httpx2.RequestError):
            await guard.handle_async_request(httpx2.Request("POST", "https://offline.invalid"))
        assert events == []
    finally:
        callback.cancel()


async def test_cross_thread_stop_before_handoff_denies_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    entered, release = asyncio.Event(), asyncio.Event()
    original = httpx2.AsyncClient._send_single_request

    async def delayed(http: httpx2.AsyncClient, request: httpx2.Request) -> httpx2.Response:
        entered.set()
        await release.wait()
        return await original(http, request)

    monkeypatch.setattr(httpx2.AsyncClient, "_send_single_request", delayed)
    model = model_with_timeout(
        "openai", ObservedMockTransport(lambda _: httpx2.Response(200), events)
    )
    caller = asyncio.create_task(model.request_once(fixture.request(), now=fixture.NOW))
    try:
        await asyncio.wait_for(entered.wait(), 15)
        await asyncio.to_thread(model.request_stop)
    finally:
        release.set()
        await asyncio.gather(caller, *model.pending_owners(), return_exceptions=True)
    assert events == []
    assert caller.result().billing == "unknown"
    assert not model.pending_owners()


async def test_redirect_cannot_issue_second_transport_request() -> None:
    events: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(307, headers={"Location": "https://offline.invalid/next"})

    resolver = fixture.adapter("openai", ObservedMockTransport(handler, events))._resolver
    endpoint = cast(fixture.EndpointResolver, resolver).endpoint

    async def observe(response: httpx2.Response) -> None:
        return None

    with transport_guard(lambda: False, time.monotonic_ns() // 1000 + 5_000_000, Lock()):
        async with GuardedAsyncClient(endpoint, observe) as client:
            with pytest.raises(httpx2.RequestError):
                await client.post("https://offline.invalid", follow_redirects=True)
    assert events == ["transport_entry"]


async def test_selected_default_and_proxy_transports_are_guarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "internal.invalid")
    endpoint = replace(
        cast(
            fixture.EndpointResolver,
            fixture.adapter(
                "openai", httpx2.MockTransport(lambda _: httpx2.Response(500))
            )._resolver,
        ).endpoint,
        transport=None,
    )

    async def observe(response: httpx2.Response) -> None:
        return None

    with transport_guard(lambda: False, time.monotonic_ns() // 1000 + 1_000_000, Lock()):
        client = GuardedAsyncClient(endpoint, observe)
    try:
        proxy_url = httpx2.URL("https://remote.invalid")
        direct_url = httpx2.URL("https://internal.invalid")
        proxy = client._transport_for_url(proxy_url)
        direct = client._transport_for_url(direct_url)
        assert isinstance(proxy, GuardedTransport) and isinstance(direct, GuardedTransport)
        assert proxy.delegate is httpx2.AsyncClient._transport_for_url(client, proxy_url)
        assert direct.delegate is httpx2.AsyncClient._transport_for_url(client, direct_url)
        assert proxy.delegate is not direct.delegate
        assert isinstance(proxy.delegate, httpx2.AsyncHTTPTransport)
        assert isinstance(direct.delegate, httpx2.AsyncHTTPTransport)
    finally:
        await client.aclose()


async def test_injected_transport_lifecycle_and_context_does_not_leak() -> None:
    events: list[str] = []

    class Tracked(ObservedMockTransport):
        async def __aenter__(self) -> Self:
            events.append("enter")
            return await super().__aenter__()

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None = None,
            exc_value: BaseException | None = None,
            traceback: TracebackType | None = None,
        ) -> None:
            events.append("exit")
            await super().__aexit__(exc_type, exc_value, traceback)

        async def aclose(self) -> None:
            events.append("close")
            await super().aclose()

    endpoint = replace(
        cast(
            fixture.EndpointResolver,
            fixture.adapter(
                "openai", httpx2.MockTransport(lambda _: httpx2.Response(500))
            )._resolver,
        ).endpoint,
        transport=Tracked(lambda _: httpx2.Response(200), events),
    )

    async def observe(response: httpx2.Response) -> None:
        return None

    with pytest.raises(ValueError, match="requires an original operation guard"):
        GuardedAsyncClient(endpoint, observe)
    with transport_guard(lambda: False, time.monotonic_ns() // 1000 + 1_000_000, Lock()):
        async with GuardedAsyncClient(endpoint, observe) as client:
            response = await client.post("https://offline.invalid")
            assert response.status_code == 200
    assert events == ["enter", "transport_entry", "exit", "close"]
    with pytest.raises(ValueError, match="requires an original operation guard"):
        GuardedAsyncClient(endpoint, observe)


async def test_parallel_attempts_keep_distinct_context_guards() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    events: list[str] = []

    async def observe(response: httpx2.Response) -> None:
        return None

    async def attempt(stopped: bool) -> int | str:
        transport = ObservedMockTransport(lambda _: httpx2.Response(200), events)
        endpoint = replace(
            cast(fixture.EndpointResolver, fixture.adapter("openai", transport)._resolver).endpoint,
            transport=transport,
        )
        with transport_guard(lambda: stopped, time.monotonic_ns() // 1000 + 5_000_000, Lock()):
            async with GuardedAsyncClient(endpoint, observe) as client:
                entered.set()
                await release.wait()
                try:
                    return (await client.post("https://offline.invalid")).status_code
                except httpx2.RequestError:
                    return "denied"

    blocked = asyncio.create_task(attempt(True))
    allowed = asyncio.create_task(attempt(False))
    await asyncio.wait_for(entered.wait(), 5)
    release.set()
    assert cast(list[int | str], await asyncio.gather(blocked, allowed)) == ["denied", 200]
    assert events == ["transport_entry"]


@pytest.mark.parametrize("provider", ["openai", "google"])
async def test_qualification_cancel_fences_not_yet_delegated_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    client, order = prepared(tmp_path, monkeypatch, provider=provider)
    entered, release = asyncio.Event(), asyncio.Event()
    original = httpx2.AsyncClient._send_single_request

    async def delayed(http: httpx2.AsyncClient, request: httpx2.Request) -> httpx2.Response:
        entered.set()
        await release.wait()
        return await original(http, request)

    monkeypatch.setattr(httpx2.AsyncClient, "_send_single_request", delayed)
    caller = asyncio.create_task(client.request_once())
    try:
        await asyncio.wait_for(entered.wait(), 15)
        caller.cancel("qualification stopped")
        await asyncio.sleep(0)
        assert client._aborted and order == ["intent"]
    finally:
        release.set()
        await asyncio.gather(caller, *client.pending_owners(), return_exceptions=True)
    assert caller.cancelled()
    assert "post" not in order and order.count("intent") == 1
    assert not client.pending_owners()


@pytest.mark.parametrize("fault", ["legacy", "changed_guard"])
async def test_qualification_old_or_changed_guard_pins_cannot_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from nexus.harness import qualification_client as qualification_module

    original, order = prepared(tmp_path, monkeypatch)
    current = _sdk_snapshot()
    if fault == "legacy":
        legacy = SdkPins.model_validate(
            {
                "versions": tuple(
                    item
                    for item in current.versions
                    if item.distribution in LEGACY_SDK_DISTRIBUTIONS
                ),
                "files": tuple(item for item in current.files if item.module in LEGACY_SDK_MODULES),
            }
        )
        recipe = original._recipe.model_copy(update={"sdk_pins": legacy})
        client = QualificationClient(
            original._factory,
            original._effects,
            original._lease,
            original._identity,
            recipe,
            original._request,
            original._resolver,
            original._store,
            end_us=original._end,
        )
    else:
        client = original
        changed_files = tuple(
            item.model_copy(update={"sha256": "f" * 64})
            if item.module == "nexus.core.llm.company_transport"
            else item
            for item in current.files
        )
        changed = SdkPins(versions=current.versions, files=changed_files)

        async def changed_snapshot() -> SdkPins:
            return changed

        monkeypatch.setattr(qualification_module, "capture_sdk_pins", changed_snapshot)
    with pytest.raises(ValueError, match="SDK sources/versions differ"):
        await client.request_once()
    assert order == [] and not client.pending_owners()


async def test_qualification_endpoint_timeout_does_not_replace_original_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, order = prepared(tmp_path, monkeypatch)
    original_resolve = client._resolver.resolve

    class SlowSyntheticTransport(httpx2.AsyncBaseTransport):
        def __init__(self, delegate: httpx2.AsyncBaseTransport) -> None:
            self.delegate = delegate

        async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
            await asyncio.sleep(0.1)
            return await self.delegate.handle_async_request(request)

        async def aclose(self) -> None:
            await self.delegate.aclose()

    async def resolve(endpoint_id: str) -> ServerEndpoint:
        endpoint = await original_resolve(endpoint_id)
        return replace(
            endpoint,
            timeout_seconds=0.05,
            transport=SlowSyntheticTransport(cast(httpx2.AsyncBaseTransport, endpoint.transport)),
        )

    monkeypatch.setattr(client._resolver, "resolve", resolve)
    result = await client.request_once()
    assert result.provider_result.billing == "known" and result.record is not None
    assert order == ["intent", "post", "receipt"]
    assert not client.pending_owners()
