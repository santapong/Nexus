"""Opt-in native worker transport retains the verified expiry through client setup awaits."""

from datetime import UTC, datetime

import httpx
from pydantic import SecretStr

from nexus.company.notifications.contracts import OwnerRecipientPolicy
from nexus.company.notifications.resend_transport import ResendTransport
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    WorkerIdentityDeniedError,
)


class CredentialedResendTransport(ResendTransport):
    """No retries or credential renewal; only the native dispatcher supplies call authority."""

    def __init__(
        self,
        recipient: OwnerRecipientPolicy,
        api_key: SecretStr | None,
        witness: AuthenticatedWorkerIdentity,
        *,
        enabled: bool = False,
        transport: httpx.MockTransport | None = None,
    ) -> None:
        if not isinstance(witness, AuthenticatedWorkerIdentity):
            raise WorkerIdentityDeniedError("Notification worker authentication is unavailable")
        self.witness = witness
        super().__init__(recipient, api_key, enabled=enabled, transport=transport)

    async def _request(
        self, method: str, path: str, *, payload: bytes | None = None, key: str | None = None
    ) -> tuple[int, bytes]:
        """No setup await may consume the credential lifetime before the HTTP issue boundary."""
        self.witness.require_time(datetime.now(UTC))
        return await super()._request(method, path, payload=payload, key=key)
