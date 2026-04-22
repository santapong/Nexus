"""Analytics API — agent performance metrics and cost breakdown.

Aggregates data from existing llm_usage and tasks tables to provide
observability into agent performance, cost trends, and system health.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from litestar import Controller, Request, get, post
from litestar.params import Parameter
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.auth import get_auth_user_from_request
from nexus.db.models import Agent, DeadLetter, FeedbackSignal, LLMUsage, Task, TaskStatus
from nexus.settings import settings

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
    """Dead letter queue statistics per topic."""

    topic: str
    count: int
    oldest: str | None = None
    newest: str | None = None


class DeadLetterResponse(BaseModel):
    """Dead letter queue overview."""

    total_dead_letters: int
    unresolved: int
    by_topic: list[DeadLetterStats]


class DeadLetterResolveResponse(BaseModel):
    """Response after resolving a dead letter."""

    id: str
    resolved: bool


class ProviderQuota(BaseModel):
    provider: str
    tokens_used_today: int
    daily_limit: int
    utilization_pct: float
    status: str


class QuotaResponse(BaseModel):
    date: str
    providers: list[ProviderQuota]


class RecentLLMCall(BaseModel):
    task_id: str
    model_name: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    created_at: str


class AgentCostDetailResponse(BaseModel):
    agent_id: str
    agent_role: str
    agent_name: str
    period: str
    total_cost_usd: float
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    cost_per_task_avg: float
    by_model: list[CostByModel]
    recent_calls: list[RecentLLMCall]


class TriggerPromptReviewRequest(BaseModel):
    agent_role: str
    reason: str = "manual_trigger"


class TriggerPromptReviewResponse(BaseModel):
    triggered: bool
    agent_role: str
    message: str


# ── Phase 9 Track 1: approval-rate metric from feedback_signals ────────────


class RoleApprovalMetric(BaseModel):
    """Mean dual-score approval rate for a single agent role."""

    role: str
    mean_helpful: float  # 0.0–1.0
    mean_safe: float  # 0.0–1.0
    n_helpful: int
    n_safe: int


class ApprovalRatesResponse(BaseModel):
    """Per-role approval rates computed from the feedback_signals table."""

    period: str
    by_role: list[RoleApprovalMetric]
    overall_helpful: float
    overall_safe: float
    total_submissions: int  # distinct (task_id, user) pairs approximated by helpful count


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


def _get_workspace_id(request: Request[Any, Any, Any]) -> str | None:
    auth_user = get_auth_user_from_request(request)
    return auth_user.workspace_id if auth_user is not None else None


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
        cutoff = _parse_period(period)

        agent_result = await db_session.execute(
            select(Agent).where(Agent.is_active.is_(True)).order_by(Agent.role)
        )
        agents = agent_result.scalars().all()
        agent_map = {str(a.id): a for a in agents}

        task_query = (
            select(
                Task.assigned_agent_id,
                func.count(Task.id).label("total"),
                func.count(Task.id)
                .filter(Task.status == TaskStatus.COMPLETED.value)
                .label("completed"),
                func.count(Task.id).filter(Task.status == TaskStatus.FAILED.value).label("failed"),
                func.avg(Task.tokens_used).label("avg_tokens"),
                func.avg(func.extract("epoch", Task.completed_at - Task.started_at))
                .filter(Task.completed_at.isnot(None), Task.started_at.isnot(None))
                .label("avg_dur"),
            )
            .where(Task.assigned_agent_id.in_(list(agent_map.keys())))
            .group_by(Task.assigned_agent_id)
        )

        if cutoff:
            task_query = task_query.where(Task.created_at >= cutoff)

        task_rows = (await db_session.execute(task_query)).all()
        task_stats = {row.assigned_agent_id: row for row in task_rows}

        cost_query = (
            select(
                LLMUsage.agent_id,
                func.coalesce(func.sum(LLMUsage.cost_usd), 0.0).label("cost"),
            )
            .where(LLMUsage.agent_id.in_(list(agent_map.keys())))
            .group_by(LLMUsage.agent_id)
        )
        if cutoff:
            cost_query = cost_query.where(LLMUsage.created_at >= cutoff)

        cost_rows = (await db_session.execute(cost_query)).all()
        cost_map = {row.agent_id: float(row.cost) for row in cost_rows}

        metrics: list[AgentPerformanceMetric] = []
        grand_total = 0
        grand_completed = 0
        grand_cost = 0.0

        for agent in agents:
            aid = str(agent.id)
            stats = task_stats.get(aid)
            total = stats.total if stats else 0
            completed = stats.completed if stats else 0
            failed = stats.failed if stats else 0
            avg_tokens = float(stats.avg_tokens or 0) if stats else 0.0
            avg_dur = float(stats.avg_dur) if stats and stats.avg_dur else None
            agent_cost = cost_map.get(aid, 0.0)

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
        cutoff = _parse_period(period)

        model_query = (
            select(
                LLMUsage.model_name,
                func.count(LLMUsage.id).label("calls"),
                func.sum(LLMUsage.input_tokens).label("input_tok"),
                func.sum(LLMUsage.output_tokens).label("output_tok"),
                func.sum(LLMUsage.cost_usd).label("cost"),
            )
            .group_by(LLMUsage.model_name)
            .order_by(func.sum(LLMUsage.cost_usd).desc())
        )

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

        role_query = (
            select(
                Agent.role,
                func.count(LLMUsage.id).label("calls"),
                func.sum(LLMUsage.cost_usd).label("cost"),
            )
            .join(Agent, Agent.id == LLMUsage.agent_id)
            .group_by(Agent.role)
            .order_by(func.sum(LLMUsage.cost_usd).desc())
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

    @get("/costs/{agent_id:str}")
    async def get_agent_cost_detail(
        self,
        agent_id: str,
        db_session: AsyncSession,
        period: str = Parameter(query="period", default="30d"),
    ) -> AgentCostDetailResponse | dict[str, str]:
        cutoff = _parse_period(period)

        agent_result = await db_session.execute(select(Agent).where(Agent.id == agent_id))
        agent = agent_result.scalar_one_or_none()
        if agent is None:
            return {"error": f"Agent {agent_id} not found"}

        model_query = (
            select(
                LLMUsage.model_name,
                func.count(LLMUsage.id).label("calls"),
                func.sum(LLMUsage.input_tokens).label("input_tok"),
                func.sum(LLMUsage.output_tokens).label("output_tok"),
                func.sum(LLMUsage.cost_usd).label("cost"),
            )
            .where(LLMUsage.agent_id == agent_id)
            .group_by(LLMUsage.model_name)
            .order_by(func.sum(LLMUsage.cost_usd).desc())
        )

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

        total_cost = sum(m.total_cost_usd for m in by_model)
        total_calls = sum(m.total_calls for m in by_model)
        total_input = sum(m.total_input_tokens for m in by_model)
        total_output = sum(m.total_output_tokens for m in by_model)

        task_count_query = select(func.count(Task.id)).where(Task.assigned_agent_id == agent_id)
        if cutoff:
            task_count_query = task_count_query.where(Task.created_at >= cutoff)
        task_count = (await db_session.execute(task_count_query)).scalar() or 0
        cost_per_task = total_cost / task_count if task_count > 0 else 0.0

        recent_query = (
            select(LLMUsage)
            .where(LLMUsage.agent_id == agent_id)
            .order_by(LLMUsage.created_at.desc())
            .limit(20)
        )
        recent_result = await db_session.execute(recent_query)
        recent_rows = recent_result.scalars().all()

        recent_calls = [
            RecentLLMCall(
                task_id=str(r.task_id),
                model_name=r.model_name,
                input_tokens=r.input_tokens,
                output_tokens=r.output_tokens,
                cost_usd=round(r.cost_usd, 6),
                created_at=str(r.created_at),
            )
            for r in recent_rows
        ]

        return AgentCostDetailResponse(
            agent_id=agent_id,
            agent_role=agent.role,
            agent_name=agent.name,
            period=period,
            total_cost_usd=round(total_cost, 6),
            total_calls=total_calls,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            cost_per_task_avg=round(cost_per_task, 6),
            by_model=by_model,
            recent_calls=recent_calls,
        )

    @get("/approval-rates")
    async def get_approval_rates(
        self,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
        period: str = Parameter(query="period", default="30d"),
    ) -> ApprovalRatesResponse:
        """Per-role mean approval rates from the feedback_signals table.

        Joins feedback_signals → tasks → agents so rows are filtered by the
        caller's workspace (via tasks.workspace_id) and grouped by agent role.
        Returns one RoleApprovalMetric per role that has any feedback, plus
        overall helpful/safe means weighted by submission count.

        Args:
            request: Litestar request (for workspace extraction).
            db_session: Async database session.
            period: Time window filter ('7d', '30d', '90d', 'all').
        """
        workspace_id = _get_workspace_id(request)
        cutoff = _parse_period(period)

        query = (
            select(
                Agent.role,
                FeedbackSignal.signal_type,
                func.count(FeedbackSignal.id).label("n"),
                func.avg(FeedbackSignal.signal_value).label("mean"),
            )
            .join(Task, Task.id == FeedbackSignal.task_id)
            .join(Agent, Agent.id == FeedbackSignal.agent_id)
            .where(FeedbackSignal.signal_type.in_(["helpful", "safe"]))
            .group_by(Agent.role, FeedbackSignal.signal_type)
        )
        if workspace_id:
            query = query.where(Task.workspace_id == workspace_id)
        if cutoff:
            query = query.where(FeedbackSignal.created_at >= cutoff)

        rows = (await db_session.execute(query)).all()

        by_role: dict[str, dict[str, float | int]] = {}
        for row in rows:
            bucket = by_role.setdefault(
                row.role,
                {"mean_helpful": 0.0, "mean_safe": 0.0, "n_helpful": 0, "n_safe": 0},
            )
            if row.signal_type == "helpful":
                bucket["mean_helpful"] = round(float(row.mean or 0.0), 3)
                bucket["n_helpful"] = int(row.n)
            elif row.signal_type == "safe":
                bucket["mean_safe"] = round(float(row.mean or 0.0), 3)
                bucket["n_safe"] = int(row.n)

        role_metrics = [
            RoleApprovalMetric(
                role=role,
                mean_helpful=float(data["mean_helpful"]),
                mean_safe=float(data["mean_safe"]),
                n_helpful=int(data["n_helpful"]),
                n_safe=int(data["n_safe"]),
            )
            for role, data in sorted(by_role.items())
        ]

        total_helpful_n = sum(r.n_helpful for r in role_metrics)
        total_safe_n = sum(r.n_safe for r in role_metrics)
        overall_helpful = (
            sum(r.mean_helpful * r.n_helpful for r in role_metrics) / total_helpful_n
            if total_helpful_n > 0
            else 0.0
        )
        overall_safe = (
            sum(r.mean_safe * r.n_safe for r in role_metrics) / total_safe_n
            if total_safe_n > 0
            else 0.0
        )

        return ApprovalRatesResponse(
            period=period,
            by_role=role_metrics,
            overall_helpful=round(overall_helpful, 3),
            overall_safe=round(overall_safe, 3),
            total_submissions=total_helpful_n,
        )

    @get("/dead-letters")
    async def get_dead_letters(
        self,
        db_session: AsyncSession,
        resolved: bool | None = Parameter(query="resolved", default=None, required=False),
    ) -> DeadLetterResponse:
        base_filter = []
        if resolved is True:
            base_filter.append(DeadLetter.resolved_at.isnot(None))
        elif resolved is False:
            base_filter.append(DeadLetter.resolved_at.is_(None))

        stats_query = (
            select(
                DeadLetter.source_topic,
                func.count(DeadLetter.id).label("count"),
                func.min(DeadLetter.created_at).label("oldest"),
                func.max(DeadLetter.created_at).label("newest"),
            )
            .where(*base_filter)
            .group_by(DeadLetter.source_topic)
        )

        rows = (await db_session.execute(stats_query)).all()

        by_topic = [
            DeadLetterStats(
                topic=row.source_topic,
                count=row.count,
                oldest=str(row.oldest) if row.oldest else None,
                newest=str(row.newest) if row.newest else None,
            )
            for row in rows
        ]

        total = sum(s.count for s in by_topic)

        unresolved_query = select(func.count(DeadLetter.id)).where(DeadLetter.resolved_at.is_(None))
        unresolved = (await db_session.execute(unresolved_query)).scalar() or 0

        return DeadLetterResponse(
            total_dead_letters=total,
            unresolved=unresolved,
            by_topic=by_topic,
        )

    @post("/dead-letters/{dead_letter_id:str}/resolve")
    async def resolve_dead_letter(
        self,
        dead_letter_id: str,
        db_session: AsyncSession,
    ) -> DeadLetterResolveResponse:
        stmt = select(DeadLetter).where(DeadLetter.id == dead_letter_id)
        result = await db_session.execute(stmt)
        record = result.scalar_one_or_none()

        if record is None:
            return DeadLetterResolveResponse(id=dead_letter_id, resolved=False)

        record.resolved_at = datetime.now(UTC)
        await db_session.commit()

        logger.info("dead_letter_resolved", dead_letter_id=dead_letter_id)
        return DeadLetterResolveResponse(id=dead_letter_id, resolved=True)

    @get("/quota")
    async def get_quota(self, db_session: AsyncSession) -> QuotaResponse:
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

        usage_rows = await db_session.execute(
            select(
                LLMUsage.model_name,
                func.sum(LLMUsage.input_tokens + LLMUsage.output_tokens).label("tokens"),
            )
            .where(LLMUsage.created_at >= today_start)
            .group_by(LLMUsage.model_name)
        )

        provider_tokens: dict[str, int] = {}
        for row in usage_rows.all():
            name: str = row.model_name or ""
            if name.startswith("claude") or "anthropic" in name:
                provider = "anthropic"
            elif name.startswith("gemini") or "google" in name:
                provider = "google"
            elif name.startswith("groq:") or "groq" in name:
                provider = "groq"
            elif name.startswith("mistral:") or "mistral" in name:
                provider = "mistral"
            elif (
                name.startswith("gpt")
                or name.startswith("openai:")
                or name.startswith("o1")
                or name.startswith("o3")
            ):
                provider = "openai"
            else:
                provider = "other"
            provider_tokens[provider] = provider_tokens.get(provider, 0) + int(row.tokens or 0)

        limits: dict[str, int] = {
            "groq": getattr(settings, "groq_daily_token_limit", 500_000),
            "anthropic": getattr(settings, "anthropic_daily_token_limit", 1_000_000),
            "google": getattr(settings, "google_daily_token_limit", 1_000_000),
            "openai": getattr(settings, "openai_daily_token_limit", 1_000_000),
            "mistral": getattr(settings, "mistral_daily_token_limit", 1_000_000),
        }

        quotas: list[ProviderQuota] = []
        for provider, limit in limits.items():
            used = provider_tokens.get(provider, 0)
            pct = round(used / limit * 100, 1) if limit > 0 else 0.0
            if pct >= 90:
                status = "critical"
            elif pct >= 70:
                status = "warning"
            else:
                status = "ok"
            quotas.append(
                ProviderQuota(
                    provider=provider,
                    tokens_used_today=used,
                    daily_limit=limit,
                    utilization_pct=pct,
                    status=status,
                )
            )

        return QuotaResponse(
            date=today_start.strftime("%Y-%m-%d"),
            providers=quotas,
        )

    @post("/trigger-prompt-review")
    async def trigger_prompt_review(
        self,
        data: TriggerPromptReviewRequest,
        db_session: AsyncSession,
    ) -> TriggerPromptReviewResponse:
        failed_task_query = (
            select(Task)
            .join(Agent, Agent.id == Task.assigned_agent_id, isouter=True)
            .where(
                Task.status == TaskStatus.FAILED.value,
                Agent.role == data.agent_role,
            )
            .order_by(Task.created_at.desc())
            .limit(1)
        )
        result = await db_session.execute(failed_task_query)
        failed_task = result.scalar_one_or_none()

        if not failed_task:
            return TriggerPromptReviewResponse(
                triggered=False,
                agent_role=data.agent_role,
                message=f"No recent failed tasks found for role '{data.agent_role}'",
            )

        try:
            import uuid

            from nexus.core.kafka.producer import publish
            from nexus.core.kafka.schemas import AgentCommand
            from nexus.core.kafka.topics import Topics

            command = AgentCommand(
                task_id=uuid.uuid4(),
                trace_id=uuid.uuid4(),
                agent_id="analytics-api",
                payload={
                    "source_task_id": str(failed_task.id),
                    "agent_role": data.agent_role,
                    "trigger_reason": data.reason,
                },
                target_role="prompt_creator",
                instruction=(
                    f"Analyze recent failures for the '{data.agent_role}' agent role "
                    f"and propose an improved system prompt. "
                    f"Reference failed task ID: {failed_task.id}. "
                    f"Trigger reason: {data.reason}."
                ),
            )
            await publish(Topics.AGENT_COMMANDS, command, key=str(command.task_id))

            logger.info(
                "prompt_review_triggered",
                agent_role=data.agent_role,
                source_task_id=str(failed_task.id),
                reason=data.reason,
            )

            return TriggerPromptReviewResponse(
                triggered=True,
                agent_role=data.agent_role,
                message=(
                    f"Prompt Creator triggered for role '{data.agent_role}' "
                    f"based on task {failed_task.id}."
                ),
            )

        except Exception as exc:
            logger.error(
                "prompt_review_trigger_failed",
                agent_role=data.agent_role,
                error=str(exc),
            )
            return TriggerPromptReviewResponse(
                triggered=False,
                agent_role=data.agent_role,
                message=f"Failed to trigger prompt review: {exc}",
            )

    @get("/agent-cost-alerts")
    async def get_agent_cost_alerts(
        self,
        db_session: AsyncSession,
    ) -> dict[str, object]:
        from nexus.core.llm.cost_alerts import get_all_agent_cost_status

        statuses = await get_all_agent_cost_status(db_session)
        return {"alerts": statuses}

    @get("/provider-health")
    async def get_provider_health(
        self,
        db_session: AsyncSession,
    ) -> dict[str, object]:
        from nexus.core.llm.provider_health import get_all_provider_health

        providers = await get_all_provider_health()
        return {"providers": providers}

    @get("/model-benchmarks/{agent_role:str}")
    async def get_model_benchmarks(
        self,
        agent_role: str,
        db_session: AsyncSession,
        model_name: str | None = Parameter(query="model", default=None, required=False),
    ) -> dict[str, object]:
        from nexus.core.llm.benchmarking import get_benchmark_history

        results = await get_benchmark_history(db_session, agent_role, model_name=model_name)
        return {"benchmarks": results, "agent_role": agent_role}
