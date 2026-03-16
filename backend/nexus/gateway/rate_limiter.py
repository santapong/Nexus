"""Per-token rate limiting for A2A inbound requests.

Uses a sliding window counter in Redis db:1 to enforce per-token
requests-per-minute (RPM) limits. Each token has its own counter.
"""
from __future__ import annotations

import time

import structlog

from nexus.redis.clients import redis_cache

logger = structlog.get_logger()

_WINDOW_TTL = 120  # 2 minutes — covers current + previous minute


async def check_rate_limit(
    token_hash: str, rpm_limit: int
) -> tuple[bool, int]:
    """Check if a token is within its rate limit.

    Uses a per-minute counter in Redis. Returns whether the request
    is allowed and how many requests remain in the current window.

    Args:
        token_hash: SHA-256 hash of the bearer token.
        rpm_limit: Maximum requests per minute for this token.

    Returns:
        Tuple of (allowed, remaining). allowed is False if over limit.
    """
    window = int(time.time() // 60)
    key = f"ratelimit:a2a:{token_hash[:16]}:{window}"

    current = await redis_cache.incr(key)
    if current == 1:
        await redis_cache.expire(key, _WINDOW_TTL)

    remaining = max(0, rpm_limit - current)
    allowed = current <= rpm_limit

    if not allowed:
        logger.warning(
            "a2a_rate_limit_exceeded",
            token_hash_prefix=token_hash[:8],
            current=current,
            limit=rpm_limit,
        )

    return allowed, remaining
