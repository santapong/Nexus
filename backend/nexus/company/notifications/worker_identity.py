"""Process-only verified credential deadlines; no issuer, owner shortcut or effect authority."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

import jwt
from pydantic import SecretStr

from nexus.company.access import VerifiedIdentity
from nexus.company.management.plans import RunBinding

MAX_CREDENTIAL_CHARACTERS = 16_384
_DEVELOPMENT_KEY = "nexus-dev-secret-change-in-production"
_DENIED = "Notification worker authentication is unavailable"


class WorkerIdentityDeniedError(ValueError):
    """Constant safe authentication failure; never reflect credentials or private claims."""


class OpaqueCredentialProvider(Protocol):
    """A trusted configured source supplies an existing credential; this API issues none."""

    async def credential(self) -> SecretStr:
        """Read the actual secret token without a caller identity or owner-ID selector."""
        ...


@dataclass(frozen=True, slots=True, init=False)
class AuthenticatedWorkerIdentity:
    """A process-local time witness; current owner/member/work/effect checks remain separate."""

    identity: VerifiedIdentity
    issued_at: datetime
    expires_at: datetime

    def __init__(
        self, identity: VerifiedIdentity, issued_at: datetime, expires_at: datetime
    ) -> None:
        raise WorkerIdentityDeniedError(_DENIED)

    def require_time(self, server_now: datetime) -> None:
        """Synchronously recheck the captured credential window after the actual last await."""
        if (
            not isinstance(server_now, datetime)
            or server_now.utcoffset() is None
            or not self.issued_at <= server_now < self.expires_at
        ):
            raise WorkerIdentityDeniedError(_DENIED)


def _verified_witness(
    identity: VerifiedIdentity, issued_at: datetime, expires_at: datetime
) -> AuthenticatedWorkerIdentity:
    result = object.__new__(AuthenticatedWorkerIdentity)
    object.__setattr__(result, "identity", identity)
    object.__setattr__(result, "issued_at", issued_at)
    object.__setattr__(result, "expires_at", expires_at)
    return result


def _configuration(credentials: OpaqueCredentialProvider | None, key: SecretStr | None) -> None:
    if (
        credentials is None
        or not isinstance(key, SecretStr)
        or len(key.get_secret_value()) < 32
        or key.get_secret_value() == _DEVELOPMENT_KEY
    ):
        raise WorkerIdentityDeniedError(_DENIED)


def _verify(credential: SecretStr, key: SecretStr) -> AuthenticatedWorkerIdentity:
    if not isinstance(credential, SecretStr):
        raise WorkerIdentityDeniedError(_DENIED)
    token = credential.get_secret_value()
    if not token or token.strip() != token or len(token) > MAX_CREDENTIAL_CHARACTERS:
        raise WorkerIdentityDeniedError(_DENIED)
    try:
        claims = jwt.decode(
            token,
            key.get_secret_value(),
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "sub", "workspace_id"]},
        )
        if any(type(claims[name]) is not int for name in ("exp", "iat")) or any(
            not isinstance(claims[name], str) for name in ("sub", "workspace_id")
        ):
            raise WorkerIdentityDeniedError(_DENIED)
        issued_at = datetime.fromtimestamp(claims["iat"], UTC)
        expires_at = datetime.fromtimestamp(claims["exp"], UTC)
        if issued_at >= expires_at:
            raise WorkerIdentityDeniedError(_DENIED)
        return _verified_witness(
            VerifiedIdentity(
                principal_id=UUID(claims["sub"]), workspace_id=UUID(claims["workspace_id"])
            ),
            issued_at,
            expires_at,
        )
    except (jwt.PyJWTError, OverflowError, OSError, ValueError, TypeError, KeyError):
        raise WorkerIdentityDeniedError(_DENIED) from None


class NotificationWorkerIdentities:
    """Explicitly configured verifier; disabled by default and no automatic credential setup."""

    __slots__ = ("_credentials", "_enabled", "_signing_key")

    def __init__(
        self,
        credentials: OpaqueCredentialProvider | None = None,
        signing_key: SecretStr | None = None,
        *,
        enabled: bool = False,
    ) -> None:
        if type(enabled) is not bool:
            raise WorkerIdentityDeniedError(_DENIED)
        if enabled:
            _configuration(credentials, signing_key)
        self._credentials, self._signing_key, self._enabled = credentials, signing_key, enabled

    async def current(
        self, expected_binding: RunBinding | None = None
    ) -> AuthenticatedWorkerIdentity:
        """Verify the actual supplied token; binding equality is not current work permission."""
        if self._enabled is not True:
            raise WorkerIdentityDeniedError(_DENIED)
        _configuration(self._credentials, self._signing_key)
        assert self._credentials is not None and self._signing_key is not None
        try:
            credential = await self._credentials.credential()
        except Exception:
            # Sanitize only the external credential acquisition boundary; cancellation propagates.
            raise WorkerIdentityDeniedError(_DENIED) from None
        witness = _verify(credential, self._signing_key)
        if expected_binding is not None and (
            witness.identity.principal_id != expected_binding.actor_id
            or witness.identity.workspace_id != expected_binding.workspace_id
        ):
            raise WorkerIdentityDeniedError(_DENIED)
        witness.require_time(datetime.now(UTC))
        return witness
