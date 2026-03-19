"""Per-agent cost alerts — configurable daily budget limits per agent.

Checks agent-specific daily spending against configured limits.
Triggers alerts via Kafka (human.input_needed) and optional webhook.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.redis.clients import redis_cache
from nexus.db.models import AgentCostAlert, LLMUsage

logger = structlog.get_logger()


def _agent_daily_spend_key(agent_id: str) -> str:
    """Redis key for per-agent daily spend tracking."""
    from datetime import date

    return f"agent_daily_spend:{agent_id}:{date.today().isoformat()}"


async def check_agent_daily_cost(
    agent_id: str,
    session: AsyncSession,
) -> tuple[bool, float, float]:
    """Check if an agent has exceeded its daily cost limit.

    Args:
        agent_id: The agent to check.
        session: Database session for fallback + alert config query.

    Returns:
        Tuple of (within_budget, current_spend, limit). If no alert
        is configured, returns (True, 0.0, 0.0).
    """
    # Load alert config from DB
    stmt = select(AgentCostAlert).where(
        AgentCostAlert.agent_id == agent_id,
        AgentCostAlert.is_active.is_(True),
    )
    result = await session.execute(stmt)
    alert_config = result.scalar_one_or_none()

    if alert_config is None:
        return True, 0.0, 0.0

    limit = alert_config.daily_limit_usd
    threshold = alert_config.alert_threshold_pct

    # Try Redis first
    current_spend = 0.0
    try:
        cached = await redis_cache.get(_agent_daily_spend_key(agent_id))
        if cached is not None:
            current_spend = float(cached)
        else:
            # Redis miss — fall back to DB
            current_spend = await _query_agent_spend_from_db(agent_id, session)
    except Exception as exc:
        logger.warning(
            "redis_agent_spend_check_failed",
            agent_id=agent_id,
            error=str(exc),
        )
        current_spend = await _query_agent_spend_from_db(agent_id, session)

    # Check threshold
    within_budget = current_spend < (limit * threshold)

    if not within_budget:
        logger.warning(
            "agent_cost_alert_triggered",
            agent_id=agent_id,
            current_spend=current_spend,
            limit=limit,
            threshold_pct=threshold,
        )

    return within_budget, current_spend, limit


async def _query_agent_spend_from_db(
    agent_id: str,
    session: AsyncSession,
) -> float:
    """Query today's total spend for an agent from the database."""
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        select(func.coalesce(func.sum(LLMUsage.cost_usd), 0.0)).where(
            LLMUsage.agent_id == agent_id,
            LLMUsage.created_at >= today_start,
        )
    )
    return float(result.scalar_one())


async def record_agent_spend(agent_id: str, cost_usd: float) -> None:
    """Update the Redis counter for an agent's daily spend.

    Best-effort — if Redis is down, the DB fallback in
    check_agent_daily_cost() will still work.
    """
    try:
        key = _agent_daily_spend_key(agent_id)
        await redis_cache.incrbyfloat(key, cost_usd)
        await redis_cache.expire(key, 90000)  # 25h TTL
    except Exception as exc:
        logger.warning(
            "redis_agent_spend_update_failed",
            agent_id=agent_id,
            error=str(exc),
        )


async def get_all_agent_cost_status(
    session: AsyncSession,
) -> list[dict[str, object]]:
    """Get cost status for all agents with configured alerts.

    Returns:
        List of dicts with agent_id, current_spend, limit, pct_used.
    """
    stmt = select(AgentCostAlert).where(AgentCostAlert.is_active.is_(True))
    result = await session.execute(stmt)
    alerts = result.scalars().all()

    statuses: list[dict[str, object]] = []
    for alert in alerts:
        spend = await _query_agent_spend_from_db(alert.agent_id, session)
        pct_used = (spend / alert.daily_limit_usd * 100) if alert.daily_limit_usd > 0 else 0.0
        statuses.append(
            {
                "agent_id": alert.agent_id,
                "current_spend_usd": round(spend, 6),
                "daily_limit_usd": alert.daily_limit_usd,
                "pct_used": round(pct_used, 1),
                "alert_threshold_pct": alert.alert_threshold_pct,
                "within_budget": spend < (alert.daily_limit_usd * alert.alert_threshold_pct),
            }
        )

    return statuses
