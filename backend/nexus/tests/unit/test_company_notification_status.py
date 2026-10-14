"""Bounded private status lookup conformance with an explicit HTTP mock only."""

from datetime import timedelta
from typing import Any

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


def response_body(event: str = "delivered") -> dict[str, Any]:
    message = payload()
    return {
        "object": "email",
        "id": str(PROVIDER_ID),
        "from": message.sender,
        "to": [message.recipient],
        "subject": message.subject,
        "text": message.text,
        "html": None,
        "cc": [],
        "bcc": [],
        "reply_to": [],
        "last_event": event,
        "created_at": NOW.isoformat(),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event,state",
    [
        ("delivered", "delivered"),
        ("delivery_delayed", "delayed"),
        ("bounced", "bounced"),
        ("failed", "failed"),
        ("suppressed", "suppressed"),
        ("complained", "complained"),
        ("sent", "unknown"),
        ("opened", "unknown"),
        ("clicked", "unknown"),
    ],
)
async def test_status_exact_known_email_has_no_send_or_human_read_inference(
    event: str, state: str
) -> None:
    calls: list[httpx.Request] = []
    adapter = ResendTransport(
        recipient(),
        SecretStr("fixture-only"),
        enabled=True,
        clock=lambda: NOW,
        transport=httpx.MockTransport(
            record_response(calls, httpx.Response(200, json=response_body(event)))
        ),
    )
    async with adapter:
        result = await adapter.retrieve(payload(), PROVIDER_ID)
    assert result.outcome == "observed" and result.delivery_state == state
    assert result.provider_event == event and result.response_sha256 is not None
    assert len(calls) == 1 and calls[0].method == "GET"
    assert calls[0].url == f"https://api.resend.com/emails/{PROVIDER_ID}"
    assert "Idempotency-Key" not in calls[0].headers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch",
    [
        {"id": "other"},
        {"to": ["other@example.invalid"]},
        {"text": "different private body"},
        {"from": "other@example.invalid"},
        {"cc": ["other@example.invalid"]},
        {"html": {"malformed": True}},
        {"last_event": {"untrusted": True}},
        {"last_event": "new-undocumented-event"},
    ],
)
async def test_status_rejects_identity_content_extra_audience_or_unknown_event(
    patch: dict[str, Any],
) -> None:
    adapter = ResendTransport(
        recipient(),
        SecretStr("fixture-only"),
        enabled=True,
        clock=lambda: NOW,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response_body() | patch)),
    )
    async with adapter:
        result = await adapter.retrieve(payload(), PROVIDER_ID)
    assert result.outcome == "unavailable" and result.delivery_state == "unknown"
    assert result.provider_event is None
    assert "private body" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_final_clock_expiry_masks_status_after_awaited_lookup() -> None:
    current = [NOW]

    def response(_: httpx.Request) -> httpx.Response:
        current[0] = NOW + timedelta(hours=2)
        return httpx.Response(200, json=response_body())

    adapter = ResendTransport(
        recipient(),
        SecretStr("fixture-only"),
        enabled=True,
        clock=lambda: current[0],
        transport=httpx.MockTransport(response),
    )
    async with adapter:
        result = await adapter.retrieve(payload(), PROVIDER_ID)
    assert result.reason == "recipient_policy" and result.outcome == "blocked"
    assert result.provider_event is None and result.delivery_state == "unknown"


@pytest.mark.asyncio
async def test_poll_failure_does_not_send() -> None:
    calls: list[httpx.Request] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("fixture-sensitive-provider-detail", request=request)

    adapter = ResendTransport(
        recipient(),
        SecretStr("fixture-only"),
        enabled=True,
        clock=lambda: NOW,
        transport=httpx.MockTransport(response),
    )
    async with adapter:
        result = await adapter.retrieve(payload(), PROVIDER_ID)
    assert len(calls) == 1 and calls[0].method == "GET"
    assert result.reason == "lookup_unavailable"
    assert "fixture-sensitive" not in result.model_dump_json()
