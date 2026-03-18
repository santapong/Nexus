"""LLM token usage tracking and cost enforcement.

Tracks costs in both Redis (speed layer) and PostgreSQL (source of truth).
When Redis is unavailable, falls back to DB queries for budget checks.
"""

from __future__ import annotations

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.audit.service import AuditEventType, log_event
from nexus.core.redis.clients import redis_cache
from nexus.db.models import LLMUsage
from nexus.settings import settings

logger = structlog.get_logger()

# Cost per 1 million tokens (input, output) in USD.
_MODEL_PRICING: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.25, "output": 1.25},
    # Google Gemini
    "gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.0},
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "o3-mini": {"input": 1.10, "output": 4.40},
    # Groq (hosted, pay-per-token)
    "groq:llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "groq:llama-3.1-8b-instant": {"input": 0.05, "output": 0.08},
    # Mistral
    "mistral:mistral-large-latest": {"input": 2.0, "output": 6.0},
    "mistral:mistral-small-latest": {"input": 0.1, "output": 0.3},
    # Local models (Ollama, vLLM, etc.) — zero cost
    "ollama:llama3": {"input": 0.0, "output": 0.0},
    "ollama:codellama": {"input": 0.0, "output": 0.0},
    "ollama:mistral": {"input": 0.0, "output": 0.0},
}


def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate USD cost for an LLM call.

    Args:
        model_name: Model identifier.
        input_tokens: Number of input/prompt tokens.
        output_tokens: Number of output/completion tokens.

    Returns:
        Cost in USD, or 0.0 if model pricing is unknown.
    """
    pricing = _MODEL_PRICING.get(model_name)
    if not pricing:
        logger.warning("unknown_model_pricing", model_name=model_name)
        return 0.0
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


def _daily_spend_key() -> str:
    """Date-keyed Redis key for daily spend tracking.

    Prevents counter reset on Redis restart mid-day.
    """
    from datetime import date

    return f"daily_spend_usd:{date.today().isoformat()}"


async def check_daily_spend(
    session: AsyncSession | None = None,
) -> bool:
    """Check if daily spend limit has been reached.

    Uses date-keyed Redis counter. Falls back to DB query if Redis
    misses or fails. Only returns True (allow) as last resort.

    Args:
        session: Optional DB session for fallback query.

    Returns:
        True if within budget, False if limit reached.
    """
    limit = float(settings.daily_spend_limit_usd)

    # Try Redis first (fast path)
    try:
        current = await redis_cache.get(_daily_spend_key())
        if current is not None:
            return float(current) < limit
    except Exception as exc:
        logger.warning("redis_daily_spend_check_failed", error=str(exc))

    # Redis miss or failure — fall back to DB (source of truth)
    if session is not None:
        try:
            from datetime import UTC, datetime

            today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            result = await session.execute(
                select(func.coalesce(func.sum(LLMUsage.cost_usd), 0.0)).where(
                    LLMUsage.created_at >= today_start
                )
            )
            db_total = float(result.scalar_one())
            return db_total < limit
        except Exception as exc:
            logger.warning("db_daily_spend_check_failed", error=str(exc))

    # Both Redis and DB failed — allow but log warning
    logger.warning("daily_spend_check_fallback_allow")
    return True


async def check_task_budget(task_id: str, budget: int | None = None) -> tuple[bool, int]:
    """Check if a task is within its token budget.

    Args:
        task_id: The task to check.
        budget: Override budget (default from settings).

    Returns:
        Tuple of (within_budget, tokens_used).
    """
    limit = budget or settings.default_token_budget_per_task
    try:
        key = f"token_budget:{task_id}"
        tokens_used = await redis_cache.get(key)
        used = int(tokens_used) if tokens_used else 0
        return used < limit, used
    except Exception as exc:
        logger.warning(
            "redis_task_budget_check_failed",
            task_id=task_id,
            error=str(exc),
        )
        return True, 0  # Allow — DB is source of truth


async def record_usage(
    *,
    session: AsyncSession,
    task_id: str,
    agent_id: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    """Record LLM usage to both database and Redis counters.

    DB write is mandatory. Redis updates are best-effort — if Redis
    is down, budget tracking degrades but usage is always persisted.
    """
    # Write to database (mandatory — source of truth)
    usage = LLMUsage(
        task_id=task_id,
        agent_id=agent_id,
        model_name=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    session.add(usage)
    await session.flush()

    # Update Redis counters (best-effort)
    total_tokens = input_tokens + output_tokens
    try:
        key = f"token_budget:{task_id}"
        await redis_cache.incrby(key, total_tokens)
        await redis_cache.expire(key, 14400)  # 4h TTL
    except Exception as exc:
        logger.warning(
            "redis_token_budget_update_failed",
            task_id=task_id,
            error=str(exc),
        )

    try:
        key = _daily_spend_key()
        await redis_cache.incrbyfloat(key, cost_usd)
        await redis_cache.expire(key, 90000)  # 25h — auto-expire next day
    except Exception as exc:
        logger.warning(
            "redis_daily_spend_update_failed",
            task_id=task_id,
            error=str(exc),
        )

    # Audit: llm_call
    await log_event(
        session=session,
        task_id=task_id,
        trace_id=task_id,
        agent_id=agent_id,
        event_type=AuditEventType.LLM_CALL,
        event_data={
            "model_name": model_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
        },
    )

    logger.info(
        "llm_usage_recorded",
        task_id=task_id,
        agent_id=agent_id,
        model=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
