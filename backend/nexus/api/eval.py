"""Eval API — LLM output quality scoring endpoints.

Provides aggregate eval scores and manual eval trigger.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from litestar import Controller, get, post
from litestar.params import Parameter
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import Agent, EvalResult

logger = structlog.get_logger()


class EvalScoreEntry(BaseModel):
    """A single eval result for API response."""

    task_id: str
    overall_score: float
    relevance: float | None
    completeness: float | None
    accuracy: float | None
    formatting: float | None
    judge_model: str | None
    created_at: str


class EvalAggregateByRole(BaseModel):
    """Aggregate eval scores for a role."""

    role: str
    count: int
    mean_score: float


class EvalScoresResponse(BaseModel):
    """Aggregate eval scores response."""

    period: str
    total_evaluated: int
    mean_score: float
    by_role: list[EvalAggregateByRole]
    recent: list[EvalScoreEntry]


class EvalRunResponse(BaseModel):
    """Response after triggering an eval run."""

    triggered: bool
    total_evaluated: int
    mean_score: float
    message: str


class EvalController(Controller):
    """Eval scoring endpoints."""

    path = "/eval"

    @get("/scores")
    async def get_scores(
        self,
        db_session: AsyncSession,
        period: str = Parameter(query="period", default="7d"),
    ) -> EvalScoresResponse:
        """Get aggregate eval scores.

        Args:
            db_session: Async database session.
            period: Time period ('7d', '30d', 'all').

        Returns:
            EvalScoresResponse with aggregate and recent scores.
        """
        now = datetime.now(UTC)
        if period == "7d":
            cutoff = now - timedelta(days=7)
        elif period == "30d":
            cutoff = now - timedelta(days=30)
        else:
            cutoff = None

        # Aggregate
        agg_query = select(
            func.count(EvalResult.id).label("count"),
            func.avg(EvalResult.overall_score).label("mean"),
        )
        if cutoff:
            agg_query = agg_query.where(EvalResult.created_at >= cutoff)

        agg_row = (await db_session.execute(agg_query)).one()
        total = agg_row[0] or 0
        mean = float(agg_row[1] or 0)

        # By role (join tasks -> agents)
        from nexus.db.models import Task

        role_query = (
            select(
                Agent.role,
                func.count(EvalResult.id).label("count"),
                func.avg(EvalResult.overall_score).label("mean"),
            )
            .join(Task, Task.id == EvalResult.task_id)
            .join(Agent, Agent.id == Task.assigned_agent_id)
            .group_by(Agent.role)
        )
        if cutoff:
            role_query = role_query.where(EvalResult.created_at >= cutoff)

        role_rows = (await db_session.execute(role_query)).all()
        by_role = [
            EvalAggregateByRole(
                role=row.role,
                count=row.count,
                mean_score=round(float(row.mean or 0), 3),
            )
            for row in role_rows
        ]

        # Recent results (last 20)
        recent_query = select(EvalResult).order_by(EvalResult.created_at.desc()).limit(20)
        recent_result = await db_session.execute(recent_query)
        recent_records = recent_result.scalars().all()

        recent = [
            EvalScoreEntry(
                task_id=str(r.task_id),
                overall_score=r.overall_score,
                relevance=r.relevance,
                completeness=r.completeness,
                accuracy=r.accuracy,
                formatting=r.formatting,
                judge_model=r.judge_model,
                created_at=str(r.created_at),
            )
            for r in recent_records
        ]

        return EvalScoresResponse(
            period=period,
            total_evaluated=total,
            mean_score=round(mean, 3),
            by_role=by_role,
            recent=recent,
        )

    @post("/run")
    async def trigger_eval_run(
        self,
        db_session: AsyncSession,
    ) -> EvalRunResponse:
        """Trigger a manual eval run on recent completed tasks.

        Args:
            db_session: Async database session.

        Returns:
            EvalRunResponse with results summary.
        """
        try:
            from nexus.db.session import get_session_factory
            from nexus.integrations.eval.runner import run_eval_suite

            factory = get_session_factory()
            summary = await run_eval_suite(db_session_factory=factory)

            return EvalRunResponse(
                triggered=True,
                total_evaluated=summary.total_evaluated,
                mean_score=summary.mean_score,
                message=(
                    f"Evaluated {summary.total_evaluated} tasks. "
                    f"Mean score: {summary.mean_score:.3f}"
                ),
            )
        except Exception as exc:
            logger.error("eval_run_failed", error=str(exc))
            return EvalRunResponse(
                triggered=False,
                total_evaluated=0,
                mean_score=0.0,
                message=f"Eval run failed: {exc}",
            )
