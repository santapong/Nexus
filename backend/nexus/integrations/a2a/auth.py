"""A2A Gateway authentication — DB-backed bearer token validation.

Tokens are stored in the a2a_tokens table with hash, allowed skills,
rate limit, and expiration. A short-lived in-memory cache avoids
hitting the DB on every request.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import A2ATokenRecord

logger = structlog.get_logger()

# ─── Cache ────────────────────────────────────────────────────────────────────

_CACHE_TTL = 300  # 5 minutes


class _CachedToken(BaseModel):
    """In-memory cache entry for a validated token."""

    token_hash: str
    name: str
    allowed_skills: list[str]
    rate_limit_rpm: int
    expires_at: datetime | None
    is_revoked: bool
    cached_at: float = Field(default_factory=time.monotonic)


_token_cache: dict[str, _CachedToken] = {}


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _hash_token(token: str) -> str:
    """Hash a bearer token using SHA-256.

    Args:
        token: The raw bearer token.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    return hashlib.sha256(token.encode()).hexdigest()


# ─── Validation ───────────────────────────────────────────────────────────────


async def validate_token(
    raw_token: str,
    *,
    skill_id: str = "general",
    db_session: AsyncSession,
) -> tuple[bool, str, int]:
    """Validate a bearer token for an A2A request.

    Args:
        raw_token: The raw bearer token from the Authorization header.
        skill_id: The skill being requested (for skill-level access control).
        db_session: Async database session.

    Returns:
        Tuple of (is_valid, error_message, rate_limit_rpm).
        error_message is empty if valid. rate_limit_rpm is 0 on failure.
    """
    if not raw_token:
        return False, "Missing bearer token", 0

    token_hash = _hash_token(raw_token)

    # Check in-memory cache first
    cached = _token_cache.get(token_hash)
    if cached and (time.monotonic() - cached.cached_at) < _CACHE_TTL:
        return _check_token_validity(cached, skill_id, token_hash)

    # Query DB
    stmt = select(A2ATokenRecord).where(A2ATokenRecord.token_hash == token_hash)
    result = await db_session.execute(stmt)
    record = result.scalar_one_or_none()

    if record is None:
        logger.warning("a2a_token_invalid", hash_prefix=token_hash[:8])
        return False, "Invalid token", 0

    # Populate cache
    cached = _CachedToken(
        token_hash=record.token_hash,
        name=record.name,
        allowed_skills=record.allowed_skills,
        rate_limit_rpm=record.rate_limit_rpm,
        expires_at=record.expires_at,
        is_revoked=record.is_revoked,
    )
    _token_cache[token_hash] = cached

    # Update last_used_at (fire and forget — don't block validation)
    try:
        await db_session.execute(
            update(A2ATokenRecord)
            .where(A2ATokenRecord.token_hash == token_hash)
            .values(last_used_at=datetime.now(UTC))
        )
        await db_session.commit()
    except Exception:
        pass  # Non-critical update

    return _check_token_validity(cached, skill_id, token_hash)


def _check_token_validity(
    token: _CachedToken, skill_id: str, token_hash: str
) -> tuple[bool, str, int]:
    """Check cached token for revocation, expiry, and skill access.

    Args:
        token: The cached token entry.
        skill_id: The requested skill ID.
        token_hash: The token hash (for logging).

    Returns:
        Tuple of (is_valid, error_message, rate_limit_rpm).
    """
    if token.is_revoked:
        logger.warning("a2a_token_revoked", name=token.name)
        return False, "Token has been revoked", 0

    if token.expires_at is not None and datetime.now(UTC) > token.expires_at:
        logger.warning(
            "a2a_token_expired",
            name=token.name,
            expired_at=str(token.expires_at),
        )
        return False, "Token expired", 0

    if "*" not in token.allowed_skills and skill_id not in token.allowed_skills:
        logger.warning(
            "a2a_token_skill_denied",
            name=token.name,
            skill_id=skill_id,
        )
        return (
            False,
            f"Token does not have access to skill: {skill_id}",
            0,
        )

    return True, "", token.rate_limit_rpm


# ─── Token management ────────────────────────────────────────────────────────


async def create_token(
    *,
    raw_token: str,
    name: str,
    allowed_skills: list[str],
    rate_limit_rpm: int,
    expires_at: datetime | None,
    db_session: AsyncSession,
) -> A2ATokenRecord:
    """Create a new A2A token in the database.

    Args:
        raw_token: The raw bearer token string.
        name: Human-readable name for the token.
        allowed_skills: Skill IDs this token can access.
        rate_limit_rpm: Requests per minute limit.
        expires_at: When the token expires. None = never.
        db_session: Async database session.

    Returns:
        The created A2ATokenRecord.
    """
    token_hash = _hash_token(raw_token)
    record = A2ATokenRecord(
        token_hash=token_hash,
        name=name,
        allowed_skills=allowed_skills,
        rate_limit_rpm=rate_limit_rpm,
        expires_at=expires_at,
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    logger.info(
        "a2a_token_created",
        name=name,
        hash_prefix=token_hash[:8],
    )
    return record


async def revoke_token(
    token_id: str,
    *,
    db_session: AsyncSession,
) -> bool:
    """Revoke an A2A token by ID.

    Args:
        token_id: UUID of the token record.
        db_session: Async database session.

    Returns:
        True if token was found and revoked, False otherwise.
    """
    stmt = select(A2ATokenRecord).where(A2ATokenRecord.id == token_id)
    result = await db_session.execute(stmt)
    record = result.scalar_one_or_none()

    if record is None:
        return False

    record.is_revoked = True
    record.revoked_at = datetime.now(UTC)
    await db_session.commit()

    # Invalidate cache
    _token_cache.pop(record.token_hash, None)

    logger.info(
        "a2a_token_revoked",
        token_id=token_id,
        name=record.name,
    )
    return True


async def seed_dev_token(db_session: AsyncSession) -> str:
    """Seed a development token for testing.

    Only runs in development environment. Generates a unique random
    token each time if no dev token exists yet.

    Args:
        db_session: Async database session.

    Returns:
        The raw token string (for logging in dev only).
    """
    import secrets

    from nexus.settings import settings

    if not settings.is_development:
        logger.info("a2a_dev_token_skipped", reason="not in development environment")
        return ""

    # Check if a dev token already exists
    stmt = select(A2ATokenRecord).where(A2ATokenRecord.name == "dev-token")
    result = await db_session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        logger.info("a2a_dev_token_exists", name="dev-token")
        return "(existing dev token — hash only in DB)"

    # Generate a unique random token
    dev_token = secrets.token_urlsafe(32)
    await create_token(
        raw_token=dev_token,
        name="dev-token",
        allowed_skills=["*"],
        rate_limit_rpm=100,
        expires_at=None,
        db_session=db_session,
    )
    logger.info("a2a_dev_token_seeded", token_preview=dev_token[:8] + "...")

    return dev_token


def invalidate_cache() -> None:
    """Clear the token cache. Used in tests."""
    _token_cache.clear()
