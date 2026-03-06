from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import LLMUsage
from nexus.redis.clients import redis_cache
from nexus.settings import settings

logger = structlog.get_logger()


async def check_daily_spend() -> bool:
    """Check if daily spend limit has been reached.

    Returns:
        True if within budget, False if limit reached.
    """
    current = await redis_cache.get("daily_spend_usd")
    if current is None:
        return True
    return float(current) < float(settings.daily_spend_limit_usd)


async def check_task_budget(task_id: str) -> tuple[bool, int]:
    """Check if a task is within its token budget.

    Returns:
        Tuple of (within_budget, tokens_used).
    """
    key = f"token_budget:{task_id}"
    tokens_used = await redis_cache.get(key)
    used = int(tokens_used) if tokens_used else 0
    return used < settings.default_token_budget_per_task, used


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
    """Record LLM usage to both database and Redis counters."""
    # Write to database
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

    # Update Redis token counter for task budget
    key = f"token_budget:{task_id}"
    total_tokens = input_tokens + output_tokens
    await redis_cache.incrby(key, total_tokens)
    await redis_cache.expire(key, 14400)  # 4h TTL

    # Update Redis daily spend counter
    await redis_cache.incrbyfloat("daily_spend_usd", cost_usd)
    # Set TTL to expire at midnight (simplified: 24h rolling)
    await redis_cache.expire("daily_spend_usd", 86400)

    logger.info(
        "llm_usage_recorded",
        task_id=task_id,
        agent_id=agent_id,
        model=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
