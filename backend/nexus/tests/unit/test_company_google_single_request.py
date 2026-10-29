"""Pinned actual SDK over offline HTTP only; no live provider or native permission."""

import copy
import json

import httpx2
import pytest

from nexus.tests.unit.test_company_provider_conformance import (
    NOW,
    Authorizer,
    adapter,
    request,
    response,
)


async def test_continuation_response_never_sends_second_post() -> None:
    captured: list[httpx2.Request] = []
    authority = Authorizer()

    def handle(wire: httpx2.Request) -> httpx2.Response:
        captured.append(wire)
        body = copy.deepcopy(response("google"))
        if len(captured) == 1:
            candidates = body["candidates"]
            assert isinstance(candidates, list) and isinstance(candidates[0], dict)
            candidates[0].update(finishReason="CONTINUATION", continuationToken="Y29udGludWU=")
        return httpx2.Response(200, json=body)

    result = await adapter(
        "google", httpx2.MockTransport(handle), authority, timeout_seconds=10
    ).request_once(request(), now=NOW)
    assert len(captured) == 1, "One native claim sent a hidden second provider POST"
    assert authority.claims == 1 and result.status == "failed"
    assert result.billing in {"known", "unknown"}
    body = json.loads(captured[0].content)
    assert body["generationConfig"]["maxOutputTokens"] == 64


@pytest.mark.parametrize(
    "finish,token_key,token",
    [
        ("CONTINUATION", "continuationToken", "Y29udGludWU="),
        (None, "continuationToken", "Y29udGludWU="),
        ("CONTINUATION", None, None),
        ("STOP", "continuationToken", "Y29udGludWU="),
        (None, "continuation_token", "Y29udGludWU="),
        (None, "continuationToken", "%%%malformed"),
        (None, "continuationToken", {"invalid": True}),
    ],
)
async def test_continuation_variants_are_failed_before_sdk_adoption(
    finish: str | None, token_key: str | None, token: object
) -> None:
    captured: list[httpx2.Request] = []
    authority = Authorizer()

    def handle(wire: httpx2.Request) -> httpx2.Response:
        captured.append(wire)
        body = response("google")
        candidates = body["candidates"]
        assert isinstance(candidates, list) and isinstance(candidates[0], dict)
        candidates[0]["finishReason"] = finish
        if token_key is not None:
            candidates[0][token_key] = token
        return httpx2.Response(200, json=body)

    result = await adapter(
        "google", httpx2.MockTransport(handle), authority, timeout_seconds=10
    ).request_once(request(), now=NOW)
    assert len(captured) == authority.claims == 1
    assert result.status == "failed" and result.billing == "known"
    assert result.usage is not None and result.usage.output_tokens == 20
    assert result.text is result.structured_json is None and result.tool_calls == ()


@pytest.mark.parametrize("broken", ["usage", "malformed", "overflow", "candidates"])
async def test_unavailable_response_cannot_trigger_another_post(broken: str) -> None:
    posts = 0

    def handle(wire: httpx2.Request) -> httpx2.Response:
        nonlocal posts
        posts += 1
        if broken == "malformed":
            return httpx2.Response(200, content=b"{not-json")
        if broken == "overflow":
            return httpx2.Response(200, content=b" " * 2_000_001)
        body = response("google")
        candidates = body["candidates"]
        assert isinstance(candidates, list) and isinstance(candidates[0], dict)
        candidates[0].update(finishReason="CONTINUATION", continuationToken="Y29udGludWU=")
        if broken == "usage":
            body.pop("usageMetadata")
        else:
            body["candidates"] = {"continuationToken": "Y29udGludWU="}
        return httpx2.Response(200, json=body)

    result = await adapter("google", httpx2.MockTransport(handle), timeout_seconds=10).request_once(
        request(), now=NOW
    )
    assert posts == 1 and result.status == "failed" and result.billing == "unknown"
    assert result.usage is None and result.text is None


@pytest.mark.parametrize("provider", ["openai", "google"])
async def test_normal_response_remains_single_request_known_usage(provider: str) -> None:
    captured: list[httpx2.Request] = []

    def handle(wire: httpx2.Request) -> httpx2.Response:
        captured.append(wire)
        return httpx2.Response(200, json=response(provider))

    result = await adapter(provider, httpx2.MockTransport(handle), timeout_seconds=10).request_once(
        request(), now=NOW
    )
    assert len(captured) == 1 and result.status == "response" and result.billing == "known"
    assert result.usage is not None and result.usage.output_tokens == 20


async def test_google_retry_remains_disabled() -> None:
    posts = 0

    def handle(wire: httpx2.Request) -> httpx2.Response:
        nonlocal posts
        posts += 1
        return httpx2.Response(503, json={"error": {"code": 503, "message": "offline busy"}})

    result = await adapter("google", httpx2.MockTransport(handle), timeout_seconds=10).request_once(
        request(), now=NOW
    )
    assert posts == 1 and result.status == "failed" and result.billing == "unknown"
