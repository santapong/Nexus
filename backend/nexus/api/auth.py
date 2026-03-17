"""JWT authentication and user management.

Provides password hashing, JWT token creation/validation, and
Litestar auth guard for protecting endpoints.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import structlog
from litestar import Request
from pydantic import BaseModel

from nexus.settings import settings

logger = structlog.get_logger()


# ─── Password hashing (SHA-256 with salt — stdlib only) ──────────────────────


def hash_password(password: str) -> str:
    """Hash a password using SHA-256 with a random salt.

    Args:
        password: Plain text password.

    Returns:
        Salt and hash concatenated as 'salt$hash'.
    """
    salt = os.urandom(16).hex()
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}${hashed}"


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a stored hash.

    Args:
        plain: Plain text password to verify.
        hashed: Stored hash in 'salt$hash' format.

    Returns:
        True if the password matches.
    """
    try:
        salt, stored_hash = hashed.split("$", 1)
        computed = hashlib.sha256(f"{salt}{plain}".encode()).hexdigest()
        return computed == stored_hash
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
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    payload = {
        "sub": user_id,
        "workspace_id": workspace_id,
        "email": email,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
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
