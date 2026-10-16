"""Actual SDK/MockTransport close ownership and stopped preissue chains, no vendor calls."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx2
import pytest

from nexus.builder.contained_query import clock_us
from nexus.core.llm.company_adapter_contracts import CompanyModelRequest, ModelRequestCancelledError
from nexus.core.llm.company_pricing import CostQuote
from nexus.tests.unit.test_company_provider_conformance import (
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
    model = adapter("openai", httpx2.MockTransport(wire))
    task = asyncio.create_task(model.request_once(request(), now=datetime.now(UTC)))
    try:
        await asyncio.wait_for(closing.wait(), 2)
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

    def wire(call: httpx2.Request) -> httpx2.Response:
        posts.append(call.method)
        return httpx2.Response(200, json=response("openai"))

    async def before(
        request: CompanyModelRequest, quote: CostQuote, eligibility_sha256: str | None
    ) -> datetime:
        await asyncio.sleep(0.05)
        return datetime.now(UTC)

    model = adapter("openai", httpx2.MockTransport(wire))
    model._before_sdk = before
    monkeypatch.setattr(model, "_operation_end_us", clock_us() + 10_000, raising=False)
    outcome = await model.request_once(request(), now=datetime.now(UTC))
    await asyncio.gather(*model.pending_owners())
    assert posts == []
    assert outcome.status == "failed" and outcome.billing == "unknown"


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
