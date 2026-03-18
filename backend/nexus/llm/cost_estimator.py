"""Cost estimator — pre-execution cost estimation for task decomposition.

CEO uses this to estimate total cost before dispatching subtasks.
Provides user-facing cost transparency.
"""

from __future__ import annotations

from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import Agent, LLMUsage
from nexus.llm.usage import _MODEL_PRICING
from nexus.settings import settings

logger = structlog.get_logger()

# Default token estimate when no historical data exists
_DEFAULT_TOKENS_PER_SUBTASK = 5000


class SubtaskEstimate(BaseModel):
    """Cost estimate for a single subtask."""

    role: str
    model_name: str
    estimated_tokens: int
    estimated_cost_usd: float


class CostEstimate(BaseModel):
    """Total cost estimate for a decomposed task."""

    subtask_count: int
    subtasks: list[SubtaskEstimate]
    total_estimated_tokens: int
    total_estimated_cost_usd: float
    confidence: str  # 'high' (based on history) | 'low' (defaults)


# Map agent roles to their default model from settings
_ROLE_MODEL_MAP: dict[str, str] = {
    "ceo": "claude-sonnet-4-20250514",
    "engineer": "claude-sonnet-4-20250514",
    "analyst": "gemini-1.5-pro",
    "writer": "claude-haiku-4-5-20251001",
    "qa": "claude-haiku-4-5-20251001",
    "prompt_creator": "claude-sonnet-4-20250514",
}


def _get_model_for_role(role: str) -> str:
    """Get the model name for an agent role.

    Args:
        role: Agent role string.

    Returns:
        Model name from settings or default mapping.
    """
    model_map = getattr(settings, "AGENT_MODEL_MAP", None)
    if model_map and role in model_map:
        return model_map[role]
    return _ROLE_MODEL_MAP.get(role, "claude-sonnet-4-20250514")


def _estimate_cost_for_tokens(model_name: str, tokens: int) -> float:
    """Estimate USD cost for a given number of tokens.

    Assumes a 60/40 input/output split for estimation purposes.

    Args:
        model_name: LLM model identifier.
        tokens: Total estimated tokens (input + output).

    Returns:
        Estimated cost in USD.
    """
    pricing = _MODEL_PRICING.get(model_name)
    if not pricing:
        return 0.0
    input_tokens = int(tokens * 0.6)
    output_tokens = int(tokens * 0.4)
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


async def estimate_task_cost(
    subtask_plan: list[dict[str, Any]],
    session: AsyncSession | None = None,
) -> CostEstimate:
    """Estimate total cost for a task decomposition plan.

    Uses historical average tokens per role from llm_usage if available,
    otherwise falls back to default estimates.

    Args:
        subtask_plan: List of subtask dicts with 'role' and 'instruction' keys.
        session: Optional DB session for historical data lookup.

    Returns:
        CostEstimate with per-subtask and total estimates.
    """
    # Try to get historical averages per role
    role_avg_tokens: dict[str, int] = {}
    has_history = False

    if session:
        try:
            avg_query = (
                select(
                    Agent.role,
                    func.avg(LLMUsage.input_tokens + LLMUsage.output_tokens).label("avg_tok"),
                )
                .join(Agent, Agent.id == LLMUsage.agent_id)
                .group_by(Agent.role)
            )

            rows = (await session.execute(avg_query)).all()
            for row in rows:
                role_avg_tokens[row.role] = int(row.avg_tok or _DEFAULT_TOKENS_PER_SUBTASK)
                has_history = True
        except Exception as exc:
            logger.warning("cost_estimator_history_failed", error=str(exc))

    subtask_estimates: list[SubtaskEstimate] = []
    total_tokens = 0
    total_cost = 0.0

    for st in subtask_plan:
        role = st.get("role", "engineer")
        model = _get_model_for_role(role)
        est_tokens = role_avg_tokens.get(role, _DEFAULT_TOKENS_PER_SUBTASK)
        est_cost = _estimate_cost_for_tokens(model, est_tokens)

        subtask_estimates.append(
            SubtaskEstimate(
                role=role,
                model_name=model,
                estimated_tokens=est_tokens,
                estimated_cost_usd=round(est_cost, 6),
            )
        )
        total_tokens += est_tokens
        total_cost += est_cost

    return CostEstimate(
        subtask_count=len(subtask_plan),
        subtasks=subtask_estimates,
        total_estimated_tokens=total_tokens,
        total_estimated_cost_usd=round(total_cost, 6),
        confidence="high" if has_history else "low",
    )
