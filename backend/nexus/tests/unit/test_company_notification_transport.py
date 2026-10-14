"""Mock HTTP conformance only; no native permit or live provider is involved."""

import httpx
import pytest
from pydantic import SecretStr

from nexus.company.notifications.resend_transport import ResendTransport
from nexus.tests.notification_rule_fixtures import (
    NOW,
    PROVIDER_ID,
    payload,
    recipient,
    record_response,
)


@pytest.mark.asyncio
async def test_disabled_transport_performs_no_request() -> None:
    calls: list[httpx.Request] = []
    adapter = ResendTransport(
        recipient(),
        SecretStr("fixture-only"),
        clock=lambda: NOW,
        transport=httpx.MockTransport(record_response(calls, httpx.Response(200))),
    )
    async with adapter:
        result = await adapter.submit(payload(), "fixture-key")
    assert result.outcome == "blocked" and result.reason == "disabled"
    assert not calls


@pytest.mark.asyncio
async def test_exact_single_request_acceptance_is_not_delivery() -> None:
    calls: list[httpx.Request] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"id": str(PROVIDER_ID)})

    adapter = ResendTransport(
        recipient(),
        SecretStr("fixture-only"),
        enabled=True,
        clock=lambda: NOW,
        transport=httpx.MockTransport(response),
    )
    async with adapter:
        result = await adapter.submit(payload(), "nexus-fixture-1")
    assert len(calls) == 1
    assert calls[0].url == "https://api.resend.com/emails"
    assert calls[0].headers["Idempotency-Key"] == "nexus-fixture-1"
    assert calls[0].content == payload().wire_bytes()
    assert result.outcome == "accepted" and result.provider_id == PROVIDER_ID
    assert result.delivery_state == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body",
    [
        (500, {}),
        (503, {}),
        (200, {}),
        (200, {"id": "not-uuid"}),
        (409, {"name": "concurrent_idempotent_requests"}),
    ],
)
async def test_uncertain_submission_never_retries(status: int, body: dict[str, str]) -> None:
    calls: list[httpx.Request] = []
    adapter = ResendTransport(
        recipient(),
        SecretStr("fixture-only"),
        enabled=True,
        clock=lambda: NOW,
        transport=httpx.MockTransport(record_response(calls, httpx.Response(status, json=body))),
    )
    async with adapter:
        result = await adapter.submit(payload(), "fixture-key")
    assert result.outcome == "unknown" and result.provider_id is None
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_redirect_is_not_followed_and_is_unknown() -> None:
    calls: list[httpx.Request] = []
    adapter = ResendTransport(
        recipient(),
        SecretStr("fixture-only"),
        enabled=True,
        clock=lambda: NOW,
        transport=httpx.MockTransport(
            record_response(
                calls, httpx.Response(307, headers={"Location": "https://untrusted.invalid"})
            )
        ),
    )
    async with adapter:
        result = await adapter.submit(payload(), "fixture-key")
    assert result.outcome == "unknown" and len(calls) == 1


@pytest.mark.asyncio
async def test_recipient_and_expired_policy_deny_before_http() -> None:
    calls: list[httpx.Request] = []
    current = [NOW]
    adapter = ResendTransport(
        recipient(),
        SecretStr("fixture-only"),
        enabled=True,
        clock=lambda: current[0],
        transport=httpx.MockTransport(record_response(calls, httpx.Response(200))),
    )
    async with adapter:
        wrong = payload().model_copy(update={"recipient": "other@example.invalid"})
        assert (await adapter.submit(wrong, "fixture-key")).reason == "recipient_policy"
        current[0] = recipient().expires_at
        assert (await adapter.submit(payload(), "fixture-key")).reason == "recipient_policy"
    assert not calls


@pytest.mark.asyncio
async def test_request_timeout_is_unknown_once_without_error_reflection() -> None:
    calls: list[httpx.Request] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("fixture-private-response-detail", request=request)

    adapter = ResendTransport(
        recipient(),
        SecretStr("fixture-only"),
        enabled=True,
        clock=lambda: NOW,
        transport=httpx.MockTransport(response),
    )
    async with adapter:
        result = await adapter.submit(payload(), "fixture-key")
    assert result.reason == "network_unknown" and result.outcome == "unknown"
    assert len(calls) == 1 and "private-response-detail" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("secret", [None, SecretStr(""), SecretStr("malformed\r\nfixture")])
async def test_missing_or_invalid_secret_is_visible_block_no_call(secret: SecretStr | None) -> None:
    calls: list[httpx.Request] = []
    adapter = ResendTransport(
        recipient(),
        secret,
        enabled=True,
        clock=lambda: NOW,
        transport=httpx.MockTransport(record_response(calls, httpx.Response(200))),
    )
    async with adapter:
        result = await adapter.submit(payload(), "fixture-key")
    assert result.reason == "configuration_missing" and not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["", "x" * 257, "key\r\nheader", "key with space"])
async def test_idempotency_key_bounded_exact_before_call(key: str) -> None:
    calls: list[httpx.Request] = []
    adapter = ResendTransport(
        recipient(),
        SecretStr("fixture-only"),
        enabled=True,
        clock=lambda: NOW,
        transport=httpx.MockTransport(record_response(calls, httpx.Response(200))),
    )
    async with adapter:
        result = await adapter.submit(payload(), key)
    assert result.reason == "invalid_key" and not calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,name,reason",
    [
        (403, "domain_not_verified", "provider_rejected"),
        (429, "rate_limit_exceeded", "provider_rejected"),
        (409, "invalid_idempotent_request", "provider_conflict"),
    ],
)
async def test_explicit_provider_rejection_is_not_delivery_or_free_bill(
    status: int, name: str, reason: str
) -> None:
    calls: list[httpx.Request] = []
    adapter = ResendTransport(
        recipient(),
        SecretStr("fixture-only"),
        enabled=True,
        clock=lambda: NOW,
        transport=httpx.MockTransport(
            record_response(
                calls, httpx.Response(status, json={"name": name, "message": "private fixture"})
            )
        ),
    )
    async with adapter:
        result = await adapter.submit(payload(), "fixture-key")
    assert result.outcome == "rejected" and result.reason == reason
    assert result.delivery_state == "unknown" and len(calls) == 1
    assert "private fixture" not in result.model_dump_json() and "cost" not in result.model_dump()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content", [b"x" * 262_145, b"[" * 1100 + b"0" + b"]" * 1100, b'{"name":{"malformed":true}}']
)
async def test_oversized_or_malformed_provider_response_is_unknown(content: bytes) -> None:
    calls: list[httpx.Request] = []
    adapter = ResendTransport(
        recipient(),
        SecretStr("fixture-only"),
        enabled=True,
        clock=lambda: NOW,
        transport=httpx.MockTransport(record_response(calls, httpx.Response(200, content=content))),
    )
    async with adapter:
        result = await adapter.submit(payload(), "fixture-key")
    assert result.outcome == "unknown" and len(calls) == 1
