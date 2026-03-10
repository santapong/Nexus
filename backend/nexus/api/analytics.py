"""Analytics API — agent performance metrics and cost breakdown.

Aggregates data from existing llm_usage and tasks tables to provide
observability into agent performance, cost trends, and system health.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from litestar import Controller, get
from litestar.params import Parameter
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import Agent, LLMUsage, Task, TaskStatus

logger = structlog.get_logger()


# ─── Response Models ─────────────────────────────────────────────────────────


class AgentPerformanceMetric(BaseModel):
    """Performance metrics for a single agent role."""

    role: str
    name: str
    total_tasks: int
    completed: int
    failed: int
    success_rate: float
    avg_tokens: float
    avg_duration_seconds: float | None
    total_cost_usd: float


class PerformanceResponse(BaseModel):
    """Aggregated performance metrics across all agents."""

    period: str
    agents: list[AgentPerformanceMetric]
    total_tasks: int
    overall_success_rate: float
    total_cost_usd: float


class CostByModel(BaseModel):
    """Cost breakdown for a single model."""

    model_name: str
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


class CostByRole(BaseModel):
    """Cost breakdown for a single agent role."""

    role: str
    total_calls: int
    total_cost_usd: float


class CostBreakdownResponse(BaseModel):
    """Cost breakdown by model and role."""

    period: str
    by_model: list[CostByModel]
    by_role: list[CostByRole]
    total_cost_usd: float
    daily_average_usd: float


class DeadLetterStats(BaseModel):
    """Dead letter queue statistics placeholder."""

    topic: str
    count: int


class DeadLetterResponse(BaseModel):
    """Dead letter queue overview."""

    total_dead_letters: int
    by_topic: list[DeadLetterStats]


# ─── Helper ──────────────────────────────────────────────────────────────────


def _parse_period(period: str) -> datetime | None:
    """Convert period string to cutoff datetime.

    Args:
        period: One of '7d', '30d', '90d', or 'all'.

    Returns:
        Cutoff datetime or None for 'all'.
    """
    now = datetime.now(UTC)
    if period == "7d":
        return now - timedelta(days=7)
    if period == "30d":
        return now - timedelta(days=30)
    if period == "90d":
        return now - timedelta(days=90)
    return None


# ─── Controller ──────────────────────────────────────────────────────────────


class AnalyticsController(Controller):
    """Analytics endpoints for agent performance and cost monitoring."""

    path = "/analytics"

    @get("/performance")
    async def get_performance(
        self,
        db_session: AsyncSession,
        period: str = Parameter(query="period", default="30d"),
    ) -> PerformanceResponse:
        """Get per-agent performance metrics.

        Aggregates task outcomes, token usage, and duration from the tasks
        and llm_usage tables. Grouped by agent role.

        Args:
            db_session: Async database session.
            period: Time period filter ('7d', '30d', '90d', 'all').

        Returns:
            PerformanceResponse with per-agent and aggregate metrics.
        """
        cutoff = _parse_period(period)

        # Get all agents
        agent_result = await db_session.execute(
            select(Agent).where(Agent.is_active.is_(True)).order_by(Agent.role)
        )
        agents = agent_result.scalars().all()

        metrics: list[AgentPerformanceMetric] = []
        grand_total = 0
        grand_completed = 0
        grand_cost = 0.0

        for agent in agents:
            # Task stats
            task_query = select(
                func.count(Task.id).label("total"),
                func.count(Task.id).filter(
                    Task.status == TaskStatus.COMPLETED.value
                ).label("completed"),
                func.count(Task.id).filter(
                    Task.status == TaskStatus.FAILED.value
                ).label("failed"),
                func.avg(Task.tokens_used).label("avg_tokens"),
            ).where(Task.assigned_agent_id == str(agent.id))

            if cutoff:
                task_query = task_query.where(Task.created_at >= cutoff)

            task_row = (await db_session.execute(task_query)).one()
            total = task_row.total or 0
            completed = task_row.completed or 0
            failed = task_row.failed or 0
            avg_tokens = float(task_row.avg_tokens or 0)

            # Average duration
            dur_query = select(
                func.avg(
                    func.extract("epoch", Task.completed_at - Task.started_at)
                ).label("avg_dur")
            ).where(
                Task.assigned_agent_id == str(agent.id),
                Task.completed_at.isnot(None),
                Task.started_at.isnot(None),
            )
            if cutoff:
                dur_query = dur_query.where(Task.created_at >= cutoff)
            dur_row = (await db_session.execute(dur_query)).one()
            avg_dur = float(dur_row.avg_dur) if dur_row.avg_dur else None

            # Cost
            cost_query = select(
                func.coalesce(func.sum(LLMUsage.cost_usd), 0.0).label("cost")
            ).where(LLMUsage.agent_id == str(agent.id))
            if cutoff:
                cost_query = cost_query.where(LLMUsage.created_at >= cutoff)
            cost_row = (await db_session.execute(cost_query)).one()
            agent_cost = float(cost_row.cost)

            success_rate = (completed / total * 100) if total > 0 else 0.0

            metrics.append(
                AgentPerformanceMetric(
                    role=agent.role,
                    name=agent.name,
                    total_tasks=total,
                    completed=completed,
                    failed=failed,
                    success_rate=round(success_rate, 1),
                    avg_tokens=round(avg_tokens, 0),
                    avg_duration_seconds=round(avg_dur, 1) if avg_dur else None,
                    total_cost_usd=round(agent_cost, 6),
                )
            )

            grand_total += total
            grand_completed += completed
            grand_cost += agent_cost

        overall_rate = (grand_completed / grand_total * 100) if grand_total > 0 else 0.0

        return PerformanceResponse(
            period=period,
            agents=metrics,
            total_tasks=grand_total,
            overall_success_rate=round(overall_rate, 1),
            total_cost_usd=round(grand_cost, 6),
        )

    @get("/costs")
    async def get_costs(
        self,
        db_session: AsyncSession,
        period: str = Parameter(query="period", default="30d"),
    ) -> CostBreakdownResponse:
        """Get cost breakdown by model and agent role.

        Aggregates from llm_usage table. Shows which models and agents
        consume the most tokens and cost.

        Args:
            db_session: Async database session.
            period: Time period filter ('7d', '30d', '90d', 'all').

        Returns:
            CostBreakdownResponse with per-model and per-role breakdowns.
        """
        cutoff = _parse_period(period)

        # By model
        model_query = select(
            LLMUsage.model_name,
            func.count(LLMUsage.id).label("calls"),
            func.sum(LLMUsage.input_tokens).label("input_tok"),
            func.sum(LLMUsage.output_tokens).label("output_tok"),
            func.sum(LLMUsage.cost_usd).label("cost"),
        ).group_by(LLMUsage.model_name).order_by(func.sum(LLMUsage.cost_usd).desc())

        if cutoff:
            model_query = model_query.where(LLMUsage.created_at >= cutoff)

        model_rows = (await db_session.execute(model_query)).all()

        by_model = [
            CostByModel(
                model_name=row.model_name,
                total_calls=row.calls,
                total_input_tokens=int(row.input_tok or 0),
                total_output_tokens=int(row.output_tok or 0),
                total_cost_usd=round(float(row.cost or 0), 6),
            )
            for row in model_rows
        ]

        # By role (join with agents table)
        role_query = select(
            Agent.role,
            func.count(LLMUsage.id).label("calls"),
            func.sum(LLMUsage.cost_usd).label("cost"),
        ).join(Agent, Agent.id == LLMUsage.agent_id).group_by(Agent.role).order_by(
            func.sum(LLMUsage.cost_usd).desc()
        )

        if cutoff:
            role_query = role_query.where(LLMUsage.created_at >= cutoff)

        role_rows = (await db_session.execute(role_query)).all()

        by_role = [
            CostByRole(
                role=row.role,
                total_calls=row.calls,
                total_cost_usd=round(float(row.cost or 0), 6),
            )
            for row in role_rows
        ]

        total_cost = sum(m.total_cost_usd for m in by_model)
        days = int(period.replace("d", "")) if period != "all" else 30
        daily_avg = total_cost / days if days > 0 else 0.0

        return CostBreakdownResponse(
            period=period,
            by_model=by_model,
            by_role=by_role,
            total_cost_usd=round(total_cost, 6),
            daily_average_usd=round(daily_avg, 6),
        )

    @get("/dead-letters")
    async def get_dead_letters(self) -> DeadLetterResponse:
        """Get dead letter queue statistics.

        Placeholder endpoint — returns topic-level counts for messages
        that failed processing after max retries. In production this
        would query Kafka admin API or a dedicated tracking table.

        Returns:
            DeadLetterResponse with per-topic dead letter counts.
        """
        # Placeholder: in a real deployment, this would query Kafka or a
        # dead_letter_log table. For now, return empty stats as the
        # infrastructure hook for the frontend.
        topics = [
            "task.queue.dead_letter",
            "agent.commands.dead_letter",
            "agent.responses.dead_letter",
            "task.results.dead_letter",
        ]
        stats = [DeadLetterStats(topic=t, count=0) for t in topics]
        return DeadLetterResponse(
            total_dead_letters=0,
            by_topic=stats,
        )
