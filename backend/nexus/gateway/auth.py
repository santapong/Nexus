"""A2A Gateway authentication.

Bearer token validation for inbound A2A calls.
Tokens are stored in a dedicated table with hash, allowed skills,
rate limit, and expiration.

For Phase 2, we use a simple in-memory token check with a seed token.
Full DB-backed token management is Phase 3.
"""
from __future__ import annotations

import hashlib
import time

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()

# ─── Token model ─────────────────────────────────────────────────────────────


class A2AToken(BaseModel):
    """Represents an A2A authentication token."""

    token_hash: str
    name: str = "default"
    allowed_skills: list[str] = Field(default_factory=lambda: ["*"])
    rate_limit_rpm: int = 60
    expires_at: float | None = None  # Unix timestamp, None = never


# ─── In-memory token store (Phase 2 — moved to DB in Phase 3) ───────────────

_token_store: dict[str, A2AToken] = {}


def _hash_token(token: str) -> str:
    """Hash a bearer token using SHA-256.

    Args:
        token: The raw bearer token.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def register_token(
    raw_token: str,
    *,
    name: str = "default",
    allowed_skills: list[str] | None = None,
    rate_limit_rpm: int = 60,
    expires_at: float | None = None,
) -> None:
    """Register a new A2A token.

    Args:
        raw_token: The raw bearer token string.
        name: Human-readable name for the token.
        allowed_skills: List of skill IDs this token can access. ['*'] = all.
        rate_limit_rpm: Requests per minute limit.
        expires_at: Unix timestamp when token expires. None = never.
    """
    token_hash = _hash_token(raw_token)
    _token_store[token_hash] = A2AToken(
        token_hash=token_hash,
        name=name,
        allowed_skills=allowed_skills or ["*"],
        rate_limit_rpm=rate_limit_rpm,
        expires_at=expires_at,
    )
    logger.info(
        "a2a_token_registered",
        name=name,
        hash_prefix=token_hash[:8],
    )


def validate_token(
    raw_token: str, *, skill_id: str = "general"
) -> tuple[bool, str]:
    """Validate a bearer token for an A2A request.

    Args:
        raw_token: The raw bearer token from the Authorization header.
        skill_id: The skill being requested (for skill-level access control).

    Returns:
        Tuple of (is_valid, error_message). error_message is empty if valid.
    """
    if not raw_token:
        return False, "Missing bearer token"

    token_hash = _hash_token(raw_token)
    token = _token_store.get(token_hash)

    if token is None:
        logger.warning(
            "a2a_token_invalid",
            hash_prefix=token_hash[:8],
        )
        return False, "Invalid token"

    # Check expiration
    if token.expires_at is not None and time.time() > token.expires_at:
        logger.warning(
            "a2a_token_expired",
            name=token.name,
            expired_at=token.expires_at,
        )
        return False, "Token expired"

    # Check skill access
    if "*" not in token.allowed_skills and skill_id not in token.allowed_skills:
        logger.warning(
            "a2a_token_skill_denied",
            name=token.name,
            skill_id=skill_id,
        )
        return False, f"Token does not have access to skill: {skill_id}"

    return True, ""


def seed_dev_token() -> str:
    """Seed a development token for testing.

    Returns:
        The raw token string (for logging/testing only).
    """
    dev_token = "nexus-dev-a2a-token-2026"
    register_token(
        dev_token,
        name="dev-token",
        allowed_skills=["*"],
        rate_limit_rpm=100,
    )
    logger.info("a2a_dev_token_seeded", token=dev_token)
    return dev_token
