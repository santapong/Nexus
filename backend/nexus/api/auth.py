"""JWT authentication and user management.

Provides password hashing, JWT token creation/validation, and
Litestar auth guard for protecting endpoints.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import structlog
from litestar import Request
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


def get_auth_user_from_request(request: Request) -> AuthUser | None:
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
