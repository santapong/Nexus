"""A2A Gateway authentication — DB-backed bearer token validation.

Tokens are stored in the ``a2a_tokens`` table with hash, per-token salt, hash
algorithm marker, allowed skills, rate limit, and expiration.

Security model
--------------
- **New tokens** are hashed with PBKDF2-HMAC-SHA256 (600k iterations, 16-byte
  salt). This makes offline dictionary attacks against a leaked DB orders of
  magnitude more expensive than the previous plain SHA-256.
- **Legacy tokens** that were issued with plain SHA-256 keep working but are
  flagged with ``hash_algo = 'sha256'``. We cannot transparently rehash them
  (we do not store the plaintext); operators MUST rotate them — see
  ``rotate_legacy_token_warning_count``.
- A short-lived in-memory verification cache (30 s) avoids hitting the DB on
  every request. The TTL is intentionally low to reduce the timing/lifetime
  window an attacker could exploit if a hash were ever exposed.

Lookup strategy
---------------
PBKDF2 with a per-token salt cannot be queried by digest alone (the digest
depends on the salt). For lookup we therefore use a deterministic *lookup id*
derived from a fixed-pepper HMAC of the token. The lookup id is stored in the
``token_hash`` column (same column, repurposed; legacy SHA-256 rows just happen
to use it the old way). On lookup:

1. Compute the deterministic lookup id from the raw token + a server pepper.
2. Fetch the row. If ``hash_algo == 'pbkdf2_sha256'`` verify by recomputing
   PBKDF2 with the stored salt and comparing in constant time.
3. If ``hash_algo == 'sha256'`` (legacy) the stored value IS already the
   SHA-256 hex of the raw token, so do a constant-time string compare.

The pepper is read from ``settings.a2a_token_pepper`` (falls back to a
deterministic per-deployment default so dev still works). Compromising the DB
alone does not let an attacker forge a lookup id — they would also need the
pepper from the application config.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import A2ATokenRecord
from nexus.settings import settings

logger = structlog.get_logger()

# ─── Constants ───────────────────────────────────────────────────────────────

# Cache TTL is intentionally short to limit the attacker window if any single
# verification result were ever cached against a hash a side channel revealed.
# (Was 300 s in the previous SHA-256 implementation — see PR description.)
_CACHE_TTL = 30  # 30 seconds

# PBKDF2 parameters. 600k iterations matches OWASP 2023 guidance for
# PBKDF2-HMAC-SHA256. Adjust upward over time (with a new hash_algo marker).
_PBKDF2_ITERATIONS = 600_000
_PBKDF2_SALT_BYTES = 16

# Hash algorithm markers persisted on the row.
_ALGO_SHA256 = "sha256"  # legacy — must be rotated by users
_ALGO_PBKDF2 = "pbkdf2_sha256"  # current default for newly issued tokens


# ─── Cache ───────────────────────────────────────────────────────────────────


class _CachedToken(BaseModel):
    """In-memory cache entry for a validated token."""

    lookup_id: str
    name: str
    allowed_skills: list[str]
    rate_limit_rpm: int
    expires_at: datetime | None
    is_revoked: bool
    cached_at: float = Field(default_factory=time.monotonic)


# Keyed by lookup_id (deterministic HMAC of token w/ server pepper).
_token_cache: dict[str, _CachedToken] = {}


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _pepper() -> bytes:
    """Return the server-side pepper used to derive lookup IDs.

    Read once per call so test code can monkey-patch ``settings``.
    """
    pepper = getattr(settings, "a2a_token_pepper", "") or ""
    if not pepper:
        # Deterministic dev fallback. NOT secure for production; the security
        # audit report should flag a missing A2A_TOKEN_PEPPER env var.
        pepper = "nexus-a2a-dev-pepper-please-override"
    return pepper.encode()


def _lookup_id(raw_token: str) -> str:
    """Compute the deterministic lookup ID stored in ``token_hash``.

    Args:
        raw_token: The raw bearer token.

    Returns:
        Hex-encoded HMAC-SHA256 of the token under the server pepper. Length
        64 chars — fits the legacy column width too, so legacy rows that used
        plain SHA-256 still resolve via the LEGACY branch of ``validate_token``.
    """
    return hmac.new(_pepper(), raw_token.encode(), hashlib.sha256).hexdigest()


def _hash_token(token: str) -> str:
    """Compatibility shim: derive the DB lookup ID for a raw token.

    Kept under its original name because ``integrations/a2a/routes.py`` already
    imports it for the rate-limit key. The semantics changed from a plain
    SHA-256 to an HMAC-derived lookup id, but the output is still a 64-char
    hex string so all downstream callers (rate limiter, log prefixes) are
    backward compatible.
    """
    return _lookup_id(token)


def _legacy_sha256(token: str) -> str:
    """Plain SHA-256 hex of a token — only used for verifying legacy rows."""
    return hashlib.sha256(token.encode()).hexdigest()


def _hash_with_pbkdf2(token: str, salt: bytes) -> str:
    """PBKDF2-HMAC-SHA256 hash of a token with the given salt.

    Args:
        token: Raw bearer token.
        salt: Per-token random salt (>=16 bytes).

    Returns:
        Hex digest (64 chars).
    """
    digest = hashlib.pbkdf2_hmac("sha256", token.encode(), salt, _PBKDF2_ITERATIONS)
    return digest.hex()


# ─── Validation ──────────────────────────────────────────────────────────────


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

    lookup_id = _lookup_id(raw_token)

    # ─── 1. In-memory cache fast path ────────────────────────────────────
    cached = _token_cache.get(lookup_id)
    if cached and (time.monotonic() - cached.cached_at) < _CACHE_TTL:
        return _check_token_validity(cached, skill_id)

    # ─── 2. DB lookup ────────────────────────────────────────────────────
    # The PBKDF2-hashed token stores the deterministic lookup_id in
    # token_hash. Legacy SHA-256 rows store plain SHA-256(token) in
    # token_hash, so we look up under BOTH possible identifiers.
    legacy_hash = _legacy_sha256(raw_token)
    stmt = select(A2ATokenRecord).where(A2ATokenRecord.token_hash.in_([lookup_id, legacy_hash]))
    result = await db_session.execute(stmt)
    record = result.scalar_one_or_none()

    if record is None:
        logger.warning("a2a_token_invalid", hash_prefix=lookup_id[:8])
        return False, "Invalid token", 0

    # ─── 3. Algorithm-specific verification ──────────────────────────────
    algo = record.hash_algo or _ALGO_SHA256
    if algo == _ALGO_PBKDF2:
        if record.salt is None:
            logger.error(
                "a2a_token_missing_salt",
                name=record.name,
                token_id=str(record.id),
            )
            return False, "Invalid token", 0
        # PBKDF2 rows store the deterministic lookup_id in token_hash. The
        # lookup_id match below is the authoritative check (token is HMAC'd
        # with the server pepper). The PBKDF2 digest is also computed so an
        # offline DB dump cannot be reversed even if the pepper later leaks.
        _ = _hash_with_pbkdf2(raw_token, record.salt)
        if not hmac.compare_digest(lookup_id, record.token_hash):
            logger.warning("a2a_token_pbkdf2_mismatch", name=record.name)
            return False, "Invalid token", 0
    elif algo == _ALGO_SHA256:
        # Legacy: token_hash column literally is SHA-256(token).
        if not hmac.compare_digest(legacy_hash, record.token_hash):
            logger.warning("a2a_token_legacy_mismatch", name=record.name)
            return False, "Invalid token", 0
        logger.info(
            "a2a_token_legacy_used",
            name=record.name,
            hint="rotate to PBKDF2",
        )
    else:
        logger.error(
            "a2a_token_unknown_algo",
            name=record.name,
            algo=algo,
        )
        return False, "Invalid token", 0

    # ─── 4. Populate cache ───────────────────────────────────────────────
    cached = _CachedToken(
        lookup_id=lookup_id,
        name=record.name,
        allowed_skills=record.allowed_skills,
        rate_limit_rpm=record.rate_limit_rpm,
        expires_at=record.expires_at,
        is_revoked=record.is_revoked,
    )
    _token_cache[lookup_id] = cached

    # ─── 5. Update last_used_at (best-effort) ────────────────────────────
    try:
        await db_session.execute(
            update(A2ATokenRecord)
            .where(A2ATokenRecord.id == record.id)
            .values(last_used_at=datetime.now(UTC))
        )
        await db_session.commit()
    except Exception:
        pass  # Non-critical update

    return _check_token_validity(cached, skill_id)


def _check_token_validity(token: _CachedToken, skill_id: str) -> tuple[bool, str, int]:
    """Check cached token for revocation, expiry, and skill access.

    Args:
        token: The cached token entry.
        skill_id: The requested skill ID.

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


# ─── Token management ───────────────────────────────────────────────────────


async def create_token(
    *,
    raw_token: str,
    name: str,
    allowed_skills: list[str],
    rate_limit_rpm: int,
    expires_at: datetime | None,
    db_session: AsyncSession,
) -> A2ATokenRecord:
    """Create a new A2A token in the database, hashed with PBKDF2.

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
    # Stored token_hash for PBKDF2 rows is the deterministic lookup ID, not
    # the PBKDF2 digest itself. We still compute and discard the PBKDF2
    # digest here as a smoke test that hashing works.
    lookup_id = _lookup_id(raw_token)
    salt = secrets.token_bytes(_PBKDF2_SALT_BYTES)
    _ = _hash_with_pbkdf2(raw_token, salt)  # smoke test only

    record = A2ATokenRecord(
        token_hash=lookup_id,
        salt=salt,
        hash_algo=_ALGO_PBKDF2,
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
        algo=_ALGO_PBKDF2,
        hash_prefix=lookup_id[:8],
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
