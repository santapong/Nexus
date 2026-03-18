"""Eval suite runner — scores completed tasks in batch.

Queries completed tasks from a time period, runs the LLM-as-judge
scorer on each, stores results in eval_results table, and computes
aggregate statistics.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select

from nexus.db.models import Agent, EvalResult, Task, TaskStatus
from nexus.eval.schemas import EvalScoreResult, EvalSummary
from nexus.eval.scorer import score_output

logger = structlog.get_logger()


async def run_eval_suite(
    *,
    since: datetime | None = None,
    limit: int = 50,
    db_session_factory: Callable[..., Any],
) -> EvalSummary:
    """Run the eval suite on completed tasks.

    Args:
        since: Only evaluate tasks completed after this time.
            Defaults to last 24 hours.
        limit: Max tasks to evaluate per run.
        db_session_factory: Factory for DB sessions.

    Returns:
        EvalSummary with aggregate scores.
    """
    if since is None:
        since = datetime.now(UTC) - timedelta(hours=24)

    async with db_session_factory() as session:
        # Fetch completed tasks with output
        stmt = (
            select(Task)
            .where(
                Task.status == TaskStatus.COMPLETED.value,
                Task.completed_at >= since,
                Task.output.isnot(None),
            )
            .order_by(Task.completed_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        tasks = result.scalars().all()

    if not tasks:
        logger.info("eval_no_tasks_found", since=str(since))
        return EvalSummary(
            total_evaluated=0,
            mean_score=0.0,
            by_role={},
            by_model={},
        )

    scores: list[EvalScoreResult] = []
    role_scores: dict[str, list[float]] = {}
    model_scores: dict[str, list[float]] = {}

    for task in tasks:
        output_str = (
            json.dumps(task.output) if isinstance(task.output, dict) else str(task.output or "")
        )

        if not output_str or output_str == "null":
            continue

        score = await score_output(
            task_id=str(task.id),
            instruction=task.instruction,
            output=output_str,
        )
        scores.append(score)

        # Persist to DB
        async with db_session_factory() as session:
            eval_record = EvalResult(
                task_id=str(task.id),
                overall_score=score.overall_score,
                relevance=score.dimensions.relevance,
                completeness=score.dimensions.completeness,
                accuracy=score.dimensions.accuracy,
                formatting=score.dimensions.formatting,
                judge_reasoning=score.judge_reasoning,
                judge_model=score.judge_model,
            )
            session.add(eval_record)
            await session.commit()

        # Aggregate by role
        async with db_session_factory() as session:
            agent_stmt = select(Agent).where(Agent.id == task.assigned_agent_id)
            agent_result = await session.execute(agent_stmt)
            agent = agent_result.scalar_one_or_none()

            if agent:
                role_scores.setdefault(agent.role, []).append(score.overall_score)
                model_scores.setdefault(agent.llm_model, []).append(score.overall_score)

    total = len(scores)
    mean = sum(s.overall_score for s in scores) / total if total > 0 else 0.0

    by_role = {role: round(sum(vals) / len(vals), 3) for role, vals in role_scores.items()}
    by_model = {model: round(sum(vals) / len(vals), 3) for model, vals in model_scores.items()}

    logger.info(
        "eval_suite_completed",
        total_evaluated=total,
        mean_score=round(mean, 3),
        roles_evaluated=list(by_role.keys()),
    )

    return EvalSummary(
        total_evaluated=total,
        mean_score=round(mean, 3),
        by_role=by_role,
        by_model=by_model,
    )
