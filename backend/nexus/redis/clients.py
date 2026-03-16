"""Redis client factory with connection pooling and retry logic.

Four clients, one per logical database role. Each uses a connection
pool with health checks and automatic reconnection.
"""
from __future__ import annotations

from redis.asyncio import ConnectionPool, Redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry

from nexus.settings import settings

_POOL_SIZE = 10
_RETRY_ON_TIMEOUT = True
_RETRY_ATTEMPTS = 3
_SOCKET_TIMEOUT = 5.0
_SOCKET_CONNECT_TIMEOUT = 5.0
_HEALTH_CHECK_INTERVAL = 30


def _make_client(db: int) -> Redis:  # type: ignore[type-arg]
    """Create an async Redis client with connection pool and retry.

    Args:
        db: Redis database number (0-3).

    Returns:
        Configured async Redis client.
    """
    retry = Retry(ExponentialBackoff(), _RETRY_ATTEMPTS)
    pool = ConnectionPool.from_url(
        f"{settings.redis_url}/{db}",
        max_connections=_POOL_SIZE,
        decode_responses=True,
        socket_timeout=_SOCKET_TIMEOUT,
        socket_connect_timeout=_SOCKET_CONNECT_TIMEOUT,
        health_check_interval=_HEALTH_CHECK_INTERVAL,
        retry=retry,
        retry_on_timeout=_RETRY_ON_TIMEOUT,
    )
    return Redis(connection_pool=pool)


# db:0 — Agent working memory (scratch pad)
redis_working = _make_client(0)

# db:1 — Task state cache, rate limiting, token budget
redis_cache = _make_client(1)

# db:2 — Real-time dashboard pub/sub, A2A SSE stream
redis_pubsub = _make_client(2)

# db:3 — Distributed locks, idempotency keys
redis_locks = _make_client(3)
