"""JWT authentication and user management.

Provides password hashing, JWT token creation/validation, symmetric
encryption helpers for stored OAuth tokens, login rate limiting, and
Litestar auth guard for protecting endpoints.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import structlog
from cryptography.fernet import Fernet, InvalidToken
from litestar import Request
from litestar.exceptions import NotAuthorizedException, TooManyRequestsException
from pydantic import BaseModel

from nexus.settings import settings

logger = structlog.get_logger()


# ─── Password hashing (PBKDF2-HMAC-SHA256 with salt — stdlib only) ───────────

_PBKDF2_ITERATIONS = 600_000  # OWASP 2023 recommendation for SHA-256


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a random salt.

    Args:
        password: Plain text password.

    Returns:
        Salt and hash concatenated as 'salt$hash' (both hex-encoded).
    """
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"{salt.hex()}${dk.hex()}"


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a stored PBKDF2 hash.

    Args:
        plain: Plain text password to verify.
        hashed: Stored hash in 'salt$hash' format.

    Returns:
        True if the password matches.
    """
    try:
        salt_hex, stored_hash = hashed.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, _PBKDF2_ITERATIONS)
        return hmac.compare_digest(dk.hex(), stored_hash)
    except (ValueError, AttributeError):
        return False


# ─── JWT Token management ────────────────────────────────────────────────────


class AuthUser(BaseModel):
    """Authenticated user context extracted from JWT."""

    user_id: str
    workspace_id: str
    email: str


def create_access_token(
    *,
    user_id: str,
    workspace_id: str,
    email: str,
) -> str:
    """Create a JWT access token.

    Args:
        user_id: User UUID.
        workspace_id: Default workspace UUID.
        email: User email.

    Returns:
        Encoded JWT token string.
    """
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub": user_id,
        "workspace_id": workspace_id,
        "email": email,
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT access token.

    Args:
        token: Encoded JWT token string.

    Returns:
        Dict with 'sub' (user_id), 'workspace_id', 'email'.

    Raises:
        jwt.InvalidTokenError: If the token is invalid or expired.
    """
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )


def get_auth_user_from_request(request: Request[Any, Any, Any]) -> AuthUser | None:
    """Extract authenticated user from request Authorization header.

    Args:
        request: Litestar request object.

    Returns:
        AuthUser if valid JWT found, None otherwise.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]
    try:
        payload = decode_access_token(token)
        return AuthUser(
            user_id=payload["sub"],
            workspace_id=payload["workspace_id"],
            email=payload["email"],
        )
    except (jwt.InvalidTokenError, KeyError) as exc:
        logger.debug("auth_token_invalid", error=str(exc))
        return None


def require_auth_user(request: Request[Any, Any, Any]) -> AuthUser:
    """Extract authenticated user, raising 401 if unauthenticated.

    Use this on endpoints that must never serve anonymous traffic — task
    and approval endpoints in particular, where falling through to
    "no workspace filter" leaks data across tenants.

    Args:
        request: Litestar request object.

    Returns:
        AuthUser populated from the request's JWT.

    Raises:
        NotAuthorizedException: When no valid Bearer token is present.
    """
    user = get_auth_user_from_request(request)
    if user is None:
        raise NotAuthorizedException(detail="Authentication required")
    return user


# ─── Symmetric encryption (Fernet) for at-rest OAuth tokens ──────────────────

_fernet_cache: Fernet | None = None


def _get_fernet() -> Fernet:
    """Return a cached Fernet instance keyed off settings.encryption_key.

    Raises:
        RuntimeError: When `NEXUS_ENCRYPTION_KEY` is missing or malformed.
    """
    global _fernet_cache
    if _fernet_cache is not None:
        return _fernet_cache

    key = settings.encryption_key.strip() if settings.encryption_key else ""
    if not key:
        raise RuntimeError(
            "NEXUS_ENCRYPTION_KEY is required for OAuth token encryption. "
            "Generate one with: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )

    try:
        _fernet_cache = Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "NEXUS_ENCRYPTION_KEY must be 32 url-safe base64 bytes "
            "(a valid Fernet key). See cryptography.fernet documentation."
        ) from exc
    return _fernet_cache


def encrypt_token(plaintext: str | None) -> str | None:
    """Encrypt a token string for at-rest storage.

    Args:
        plaintext: Raw token string (e.g., OAuth access/refresh token).
                   None passes through unchanged.

    Returns:
        Base64-encoded Fernet ciphertext, or None when input is None/empty.
    """
    if not plaintext:
        return None
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str | None) -> str | None:
    """Decrypt a Fernet-encrypted token from storage.

    Args:
        ciphertext: Fernet ciphertext produced by `encrypt_token`.
                    None or empty values pass through unchanged.

    Returns:
        Decrypted plaintext, or None when input is None/empty.

    Raises:
        InvalidToken: When ciphertext is corrupted or signed with a
            different key.
    """
    if not ciphertext:
        return None
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        logger.error("oauth_token_decrypt_failed")
        raise


# ─── Login rate limiting (per-IP + per-email sliding window) ─────────────────

_LOGIN_RATE_LIMIT_PER_MINUTE = 10
_LOGIN_RATE_WINDOW_SECONDS = 60


async def check_login_rate_limit(*, ip: str, email: str) -> tuple[bool, int]:
    """Sliding-window rate limit for login attempts.

    Independently counts attempts per remote IP and per submitted email
    address so attackers cannot rotate IPs to grind one account, nor
    spray many accounts from a single IP. Both counters must be under
    the limit for an attempt to proceed.

    Args:
        ip: Client IP address (use `0.0.0.0` when unknown).
        email: Email address from the login payload (lowercased before hashing).

    Returns:
        (allowed, retry_after_seconds). `allowed=False` indicates the
        caller should respond with 429 and `Retry-After: retry_after_seconds`.
    """
    from nexus.core.redis.clients import redis_cache

    window = int(time.time() // _LOGIN_RATE_WINDOW_SECONDS)
    ip_safe = ip or "unknown"
    email_hash = hashlib.sha256(email.lower().strip().encode()).hexdigest()[:16]
    ip_key = f"ratelimit:login:ip:{ip_safe}:{window}"
    email_key = f"ratelimit:login:email:{email_hash}:{window}"

    try:
        ip_count = await redis_cache.incr(ip_key)
        if ip_count == 1:
            await redis_cache.expire(ip_key, _LOGIN_RATE_WINDOW_SECONDS * 2)
        email_count = await redis_cache.incr(email_key)
        if email_count == 1:
            await redis_cache.expire(email_key, _LOGIN_RATE_WINDOW_SECONDS * 2)
    except Exception as exc:
        # Fail-open on Redis outage but log loudly.
        logger.warning("login_rate_limit_check_failed", error=str(exc))
        return True, 0

    if int(ip_count) > _LOGIN_RATE_LIMIT_PER_MINUTE:
        logger.warning("login_rate_limited_ip", ip=ip_safe, attempts=int(ip_count))
        return False, _LOGIN_RATE_WINDOW_SECONDS
    if int(email_count) > _LOGIN_RATE_LIMIT_PER_MINUTE:
        logger.warning("login_rate_limited_email", attempts=int(email_count))
        return False, _LOGIN_RATE_WINDOW_SECONDS
    return True, 0


async def enforce_login_rate_limit(request: Request[Any, Any, Any], email: str) -> None:
    """Enforce the login rate limit, raising 429 when exceeded.

    Convenience wrapper for login route handlers. Resolves the client IP
    from the request and translates a denied check into a Litestar
    `NotAuthorizedException` carrying a `Retry-After` header hint.

    Args:
        request: Litestar request object.
        email: Email from the login payload.

    Raises:
        NotAuthorizedException: When 10+ attempts have been seen in the
            current 60s window for either the IP or the email.
    """
    ip = request.client.host if request.client else "0.0.0.0"
    allowed, retry_after = await check_login_rate_limit(ip=ip, email=email)
    if not allowed:
        raise TooManyRequestsException(
            detail=f"Too many login attempts. Retry in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )
