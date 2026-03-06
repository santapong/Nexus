from __future__ import annotations

from redis.asyncio import Redis

from nexus.settings import settings


def _make_client(db: int) -> Redis:  # type: ignore[type-arg]
    """Create an async Redis client for a specific database number."""
    return Redis.from_url(f"{settings.redis_url}/{db}", decode_responses=True)


# db:0 — Agent working memory (scratch pad)
redis_working = _make_client(0)

# db:1 — Task state cache, rate limiting, token budget
redis_cache = _make_client(1)

# db:2 — Real-time dashboard pub/sub, A2A SSE stream
redis_pubsub = _make_client(2)

# db:3 — Distributed locks, idempotency keys
redis_locks = _make_client(3)
