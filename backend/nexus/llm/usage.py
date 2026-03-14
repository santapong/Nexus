from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.audit.service import AuditEventType, log_event
from nexus.db.models import LLMUsage
from nexus.redis.clients import redis_cache
from nexus.settings import settings

logger = structlog.get_logger()

# Cost per 1 million tokens (input, output) in USD.
# Models not listed here still work — cost defaults to 0.0 with a logged warning.
# Add pricing for any model you use to ensure accurate budget tracking.
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
        model_name: Model identifier (e.g. 'claude-sonnet-4-20250514').
        input_tokens: Number of input/prompt tokens.
        output_tokens: Number of output/completion tokens.

    Returns:
        Cost in USD, or 0.0 if model pricing is unknown.
    """
    pricing = _MODEL_PRICING.get(model_name)
    if not pricing:
        logger.warning("unknown_model_pricing", model_name=model_name)
        return 0.0
    return (
        input_tokens * pricing["input"] + output_tokens * pricing["output"]
    ) / 1_000_000


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

    # Audit: llm_call
    await log_event(
        session=session,
        task_id=task_id,
        trace_id=task_id,  # trace_id not available here; task_id as fallback
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
