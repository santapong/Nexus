"""Actual SDK/MockTransport close ownership and stopped preissue chains, no vendor calls."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import httpx2
import pytest

from nexus.builder.contained_query import clock_us
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, ModelRequestCancelledError
from nexus.core.llm.company_pricing import CostQuote
from nexus.tests.unit.test_company_provider_conformance import (
    Authorizer,
    EndpointResolver,
    adapter,
    request,
    response,
)


async def test_cancelled_actual_sdk_close_keeps_original_resource_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    closing, finish = asyncio.Event(), asyncio.Event()
    interrupted: list[BaseException] = []
    original = httpx2.AsyncClient.aclose

    async def close(client: httpx2.AsyncClient) -> None:
        closing.set()
        try:
            await finish.wait()
        except asyncio.CancelledError as error:
            interrupted.append(error)
            raise
        await original(client)

    def wire(call: httpx2.Request) -> httpx2.Response:
        calls.append(call.method)
        return httpx2.Response(200, json=response("openai"))

    monkeypatch.setattr(httpx2.AsyncClient, "aclose", close)
    model = adapter("openai", httpx2.MockTransport(wire), timeout_seconds=30)
    task = asyncio.create_task(model.request_once(request(), now=datetime.now(UTC)))
    try:
        await asyncio.wait_for(closing.wait(), 20)
        task.cancel("First caller stop")
        await asyncio.sleep(0)
        task.cancel("Repeated caller stop")
        with pytest.raises(ModelRequestCancelledError) as caught:
            await task
        assert interrupted == []  # A cancelled wrapper is not completed SDK cleanup.
        assert caught.value.result.status == "cancelled"
        assert caught.value.result.billing == "unknown"
        owners = model.pending_owners()
        assert len(owners) == 1 and not owners[0].done()
    finally:
        finish.set()
        if hasattr(model, "pending_owners"):
            await asyncio.gather(*model.pending_owners())
    assert calls == ["POST"] and model.pending_owners() == ()


async def test_shorter_original_sdk_end_cannot_issue_after_pre_sdk_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts: list[str] = []
    entered, finish = asyncio.Event(), asyncio.Event()

    def wire(call: httpx2.Request) -> httpx2.Response:
        posts.append(call.method)
        return httpx2.Response(200, json=response("openai"))

    async def before(
        request: CompanyModelRequest, quote: CostQuote, eligibility_sha256: str | None
    ) -> datetime:
        entered.set()
        await finish.wait()
        return datetime.now(UTC)

    authority = Authorizer()
    model = adapter("openai", httpx2.MockTransport(wire), authority)
    resolver = cast(EndpointResolver, model._resolver)
    resolver.endpoint = replace(resolver.endpoint, timeout_seconds=10)
    model._before_sdk = before
    # Set one original finite end before admission; never renew it after claim.
    original_end = clock_us() + 5_000_000
    monkeypatch.setattr(model, "_operation_end_us", original_end)
    caller = asyncio.create_task(model.request_once(request(), now=datetime.now(UTC)))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert authority.claims == 1 and clock_us() < original_end
        outcome = await asyncio.wait_for(caller, 8)
        assert outcome.status == "failed" and outcome.billing == "unknown"
        assert model._operation_end_us == original_end and clock_us() >= original_end
        assert model.pending_owners()
    finally:
        finish.set()
        await asyncio.gather(caller, *model.pending_owners(), return_exceptions=True)
    assert posts == []
    assert not model.pending_owners()


async def test_cancellation_during_actual_pre_sdk_check_cannot_issue_later() -> None:
    entered, finish = asyncio.Event(), asyncio.Event()
    calls: list[str] = []

    def wire(call: httpx2.Request) -> httpx2.Response:
        calls.append(call.method)
        return httpx2.Response(200, json=response("openai"))

    async def before(
        request: CompanyModelRequest, quote: CostQuote, eligibility_sha256: str | None
    ) -> datetime:
        entered.set()
        await finish.wait()
        return datetime.now(UTC)

    model = adapter("openai", httpx2.MockTransport(wire))
    model._before_sdk = before
    task = asyncio.create_task(model.request_once(request(), now=datetime.now(UTC)))
    try:
        await entered.wait()
        task.cancel("Stop before actual SDK boundary")
        with pytest.raises(ModelRequestCancelledError):
            await task
        assert calls == []
        owners = model.pending_owners()
        assert len(owners) == 1 and not owners[0].done()
        finish.set()
        await asyncio.gather(*owners)
        assert calls == []
    finally:
        finish.set()
