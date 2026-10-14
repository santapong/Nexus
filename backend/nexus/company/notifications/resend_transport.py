"""Optional infrastructure only: no installed caller, approval, retry or live credentials."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID

import httpx
from pydantic import SecretStr, TypeAdapter, ValidationError

from nexus.company.notifications.contracts import (
    IdempotencyKey,
    NotificationPayload,
    OwnerRecipientPolicy,
)
from nexus.company.notifications.delivery_contracts import (
    StatusResult,
    SubmissionResult,
    TransportReason,
)
from nexus.company.notifications.resend_responses import status_response, submission_response


class _ResponseTooLargeError(ValueError):
    pass


class ResendTransport:
    """Only a trusted one-permit native dispatcher may invoke submit; not an auth service."""

    def __init__(
        self,
        recipient: OwnerRecipientPolicy,
        api_key: SecretStr | None = None,
        *,
        enabled: bool = False,
        transport: httpx.MockTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if type(enabled) is not bool:
            raise ValueError("Transport enablement must be explicit server configuration")
        if transport is not None and not isinstance(transport, httpx.MockTransport):
            raise ValueError("Only an explicit offline HTTP mock may replace the transport")
        self._recipient = recipient
        self._key = api_key
        self._enabled = enabled
        self._clock = clock
        self._client = httpx.AsyncClient(
            base_url="https://api.resend.com",
            timeout=10.0,
            follow_redirects=False,
            transport=transport or httpx.AsyncHTTPTransport(retries=0),
            trust_env=False,
        )

    async def __aenter__(self) -> "ResendTransport":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    def _blocked(self, payload: NotificationPayload) -> TransportReason | None:
        if not self._enabled:
            return "disabled"
        if (
            self._key is None
            or not self._key.get_secret_value().strip()
            or any(ord(char) < 33 or ord(char) > 126 for char in self._key.get_secret_value())
        ):
            return "configuration_missing"
        now = self._clock()
        if (
            now.utcoffset() is None
            or not self._recipient.registered_at <= now < self._recipient.expires_at
        ):
            return "recipient_policy"
        if (payload.sender, payload.recipient) != (
            self._recipient.sender,
            self._recipient.recipient,
        ):
            return "recipient_policy"
        return None

    async def _request(
        self, method: str, path: str, *, payload: bytes | None = None, key: str | None = None
    ) -> tuple[int, bytes]:
        assert self._key is not None
        headers = {
            "Authorization": f"Bearer {self._key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        if key is not None:
            headers["Idempotency-Key"] = key
        async with asyncio.timeout(10):
            async with self._client.stream(
                method, path, content=payload, headers=headers, follow_redirects=False
            ) as response:
                content = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    content.extend(chunk)
                    if len(content) > 262_144:
                        raise _ResponseTooLargeError(
                            "Provider response exceeds the bounded envelope"
                        )
                return response.status_code, bytes(content)

    async def submit(self, payload: NotificationPayload, idempotency_key: str) -> SubmissionResult:
        reason = self._blocked(payload)
        if reason is not None:
            return SubmissionResult(outcome="blocked", reason=reason)
        try:
            TypeAdapter(IdempotencyKey).validate_python(idempotency_key)
        except ValidationError:
            return SubmissionResult(outcome="blocked", reason="invalid_key")
        try:
            status, raw = await self._request(
                "POST", "/emails", payload=payload.wire_bytes(), key=idempotency_key
            )
        except (httpx.RequestError, TimeoutError):
            return SubmissionResult(outcome="unknown", reason="network_unknown")
        except _ResponseTooLargeError:
            return SubmissionResult(outcome="unknown", reason="response_too_large")
        return submission_response(status, raw)

    async def retrieve(self, payload: NotificationPayload, provider_id: UUID) -> StatusResult:
        if not isinstance(provider_id, UUID):
            raise ValueError("Status lookup requires an exact known provider email identity")
        reason = self._blocked(payload)
        if reason is not None:
            return StatusResult(outcome="blocked", reason=reason, provider_id=provider_id)
        try:
            status, raw = await self._request("GET", f"/emails/{provider_id}")
        except (httpx.RequestError, TimeoutError, _ResponseTooLargeError):
            return StatusResult(
                outcome="unavailable", reason="lookup_unavailable", provider_id=provider_id
            )
        reason = self._blocked(payload)
        if reason is not None:
            return StatusResult(outcome="blocked", reason=reason, provider_id=provider_id)
        return status_response(status, raw, payload, provider_id)
