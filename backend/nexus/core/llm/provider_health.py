"""Provider health monitoring — track latency, error rates, availability.

Records every LLM call's latency and success/failure. Maintains a rolling
window in Redis, periodically flushed to the provider_health table.
Integrates with circuit_breaker.py for automatic failover decisions.
"""

from __future__ import annotations

import statistics
import time
from collections import defaultdict
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.llm.circuit_breaker import get_all_breaker_states, get_breaker
from nexus.core.redis.clients import redis_cache
from nexus.db.models import ProviderHealth
from nexus.settings import settings

logger = structlog.get_logger()


def _extract_provider(model_name: str) -> str:
    """Extract provider name from a model name string.

    Handles bare model names (claude-*, gemini-*, gpt-*) and prefixed ones
    (groq:, ollama:, cerebras:, openrouter:, etc.). Returns 'unknown' for
    anything that doesn't match a known pattern so health metrics still
    record without crashing.
    """
    if model_name.startswith("claude"):
        return "anthropic"
    if model_name.startswith("gemini"):
        return "google"
    openai_prefixes = ("gpt-", "o1-", "o3-")
    if model_name.startswith(openai_prefixes):
        return "openai"
    if ":" in model_name:
        return model_name.split(":")[0]
    return "unknown"


# ─── In-memory ring buffer for current window ────────────────────────────────

_call_records: dict[str, list[dict[str, float | bool]]] = defaultdict(list)
_window_start: float = time.monotonic()


async def record_call(
    model_name: str,
    latency_ms: int,
    *,
    success: bool,
    task_id: str | None = None,
) -> None:
    """Record an LLM call for health tracking.

    Args:
        model_name: The model that was called.
        latency_ms: Call duration in milliseconds.
        success: Whether the call succeeded.
        task_id: Optional task ID for logging.
    """
    provider = _extract_provider(model_name)

    _call_records[provider].append(
        {
            "latency_ms": float(latency_ms),
            "success": 1.0 if success else 0.0,
            "timestamp": time.monotonic(),
        }
    )

    # Update circuit breaker
    breaker = get_breaker(provider)
    if success:
        breaker.record_success()
    else:
        breaker.record_failure()

    # Update Redis counters (best-effort)
    try:
        key_requests = f"provider_health:{provider}:requests"
        key_errors = f"provider_health:{provider}:errors"
        key_latency = f"provider_health:{provider}:latency_sum"

        await redis_cache.incr(key_requests)
        await redis_cache.expire(key_requests, 3600)

        if not success:
            await redis_cache.incr(key_errors)
            await redis_cache.expire(key_errors, 3600)

        await redis_cache.incrbyfloat(key_latency, float(latency_ms))
        await redis_cache.expire(key_latency, 3600)
    except Exception as exc:
        logger.warning(
            "provider_health_redis_update_failed",
            provider=provider,
            error=str(exc),
        )


def get_provider_status(provider: str) -> str:
    """Get current health status for a provider from in-memory data.

    Returns:
        'healthy', 'degraded', or 'down'.
    """
    breaker_states = get_all_breaker_states()
    breaker_state = breaker_states.get(provider, "closed")

    if breaker_state == "open":
        return "down"
    if breaker_state == "half_open":
        return "degraded"

    records = _call_records.get(provider, [])
    if not records:
        return "healthy"

    # Check error rate in recent records
    recent = records[-100:]  # Last 100 calls
    errors = sum(1 for r in recent if r["success"] == 0.0)
    error_rate = errors / len(recent) if recent else 0.0

    if error_rate > 0.5:
        return "down"
    if error_rate > 0.1:
        return "degraded"

    return "healthy"


async def get_all_provider_health() -> list[dict[str, object]]:
    """Get health summary for all tracked providers."""
    breaker_states = get_all_breaker_states()
    providers = set(list(_call_records.keys()) + list(breaker_states.keys()))

    results: list[dict[str, object]] = []
    for provider in sorted(providers):
        records = _call_records.get(provider, [])
        recent = records[-100:]

        total = len(recent)
        errors = sum(1 for r in recent if r["success"] == 0.0)
        latencies = [r["latency_ms"] for r in recent if r["success"] == 1.0]

        results.append(
            {
                "provider": provider,
                "status": get_provider_status(provider),
                "circuit_breaker": breaker_states.get(provider, "closed"),
                "total_requests": total,
                "total_errors": errors,
                "error_rate": round(errors / total, 3) if total > 0 else 0.0,
                "latency_p50_ms": int(statistics.median(latencies)) if latencies else 0,
                "latency_p99_ms": int(statistics.quantiles(latencies, n=100)[-1])
                if len(latencies) >= 2
                else (int(latencies[0]) if latencies else 0),
            }
        )

    return results


async def flush_health_window(session: AsyncSession) -> None:
    """Flush the in-memory health data to the database.

    Creates a ProviderHealth record per provider for the current window.
    Called periodically by the scheduler or a background task.
    """
    global _window_start
    now = time.monotonic()
    window_minutes = settings.provider_health_window_minutes
    elapsed_minutes = (now - _window_start) / 60

    if elapsed_minutes < window_minutes:
        return

    window_start_dt = datetime.now(UTC)
    window_end_dt = window_start_dt

    for provider, records in _call_records.items():
        if not records:
            continue

        total = len(records)
        errors = sum(1 for r in records if r["success"] == 0.0)
        latencies = [r["latency_ms"] for r in records if r["success"] == 1.0]

        health_record = ProviderHealth(
            provider=provider,
            model_name=provider,  # Aggregated at provider level
            status=get_provider_status(provider),
            latency_p50_ms=int(statistics.median(latencies)) if latencies else 0,
            latency_p99_ms=int(statistics.quantiles(latencies, n=100)[-1])
            if len(latencies) >= 2
            else (int(latencies[0]) if latencies else 0),
            error_rate=round(errors / total, 3) if total > 0 else 0.0,
            total_requests=total,
            total_errors=errors,
            window_start=window_start_dt,
            window_end=window_end_dt,
        )
        session.add(health_record)

    # Reset window
    _call_records.clear()
    _window_start = now

    await session.flush()
    logger.info("provider_health_window_flushed")
