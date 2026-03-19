"""RLHF-lite feedback loop for agent improvement.

Captures human approval/rejection signals from the human_approvals table
and task ratings, then feeds them back into semantic memory as preference
data. Agents learn what "good" looks like for this specific user/company.

This is NOT full RLHF — it's a lightweight preference signal system that
improves agent behavior through memory context, not model weight updates.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import (
    AgentRole,
    EpisodicMemory,
    FeedbackSignal,
    HumanApproval,
    SemanticMemory,
    Task,
)

logger = structlog.get_logger()


class FeedbackCollector:
    """Collects and processes human feedback signals for agent improvement.

    Feedback sources:
    1. Human approvals (approved/rejected) for irreversible actions
    2. Task output ratings (thumbs up/down from dashboard)
    3. QA rework signals (how many rounds before acceptance)
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_feedback(
        self,
        *,
        task_id: str,
        agent_id: str,
        signal_type: str,
        signal_value: float,
        context: dict[str, Any] | None = None,
        trace_id: str = "",
    ) -> FeedbackSignal:
        """Record a feedback signal for an agent's work.

        Args:
            task_id: The task that generated this feedback.
            agent_id: The agent that performed the work.
            signal_type: Type of signal — 'approval', 'rating', 'rework', 'escalation'.
            signal_value: Numeric signal — 1.0 = positive, 0.0 = negative, 0.5 = neutral.
            context: Additional context about the feedback.
            trace_id: For observability.

        Returns:
            The created FeedbackSignal record.
        """
        signal = FeedbackSignal(
            id=str(uuid4()),
            task_id=task_id,
            agent_id=agent_id,
            signal_type=signal_type,
            signal_value=signal_value,
            context=context or {},
        )
        self.session.add(signal)
        await self.session.flush()

        logger.info(
            "feedback_recorded",
            task_id=task_id,
            agent_id=agent_id,
            signal_type=signal_type,
            signal_value=signal_value,
            trace_id=trace_id,
        )
        return signal

    async def collect_approval_signals(
        self,
        *,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Collect feedback signals from human approval decisions.

        Approved actions → positive signal (1.0)
        Rejected actions → negative signal (0.0)

        Args:
            since: Only collect approvals after this timestamp.

        Returns:
            List of collected signal summaries.
        """
        since = since or datetime.now(UTC) - timedelta(days=7)
        stmt = select(HumanApproval).where(
            and_(
                HumanApproval.resolved_at.is_not(None),
                HumanApproval.resolved_at >= since,
            ),
        )
        result = await self.session.execute(stmt)
        approvals = result.scalars().all()

        signals: list[dict[str, Any]] = []
        for approval in approvals:
            signal_value = 1.0 if approval.status == "approved" else 0.0
            existing = await self._check_existing_signal(
                task_id=approval.task_id,
                agent_id=approval.agent_id,
                signal_type="approval",
            )
            if existing:
                continue

            signal = await self.record_feedback(
                task_id=approval.task_id,
                agent_id=approval.agent_id,
                signal_type="approval",
                signal_value=signal_value,
                context={
                    "tool_name": approval.tool_name,
                    "action": approval.action_description,
                    "decision": approval.status,
                },
            )
            signals.append({
                "signal_id": signal.id,
                "agent_id": approval.agent_id,
                "decision": approval.status,
            })

        logger.info("approval_signals_collected", count=len(signals))
        return signals

    async def collect_rework_signals(
        self,
        *,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Collect feedback from QA rework rounds.

        0 reworks → 1.0 (perfect first attempt)
        1 rework → 0.6
        2+ reworks → 0.3
        Failed after max reworks → 0.0

        Args:
            since: Only collect tasks after this timestamp.

        Returns:
            List of collected signal summaries.
        """
        since = since or datetime.now(UTC) - timedelta(days=7)
        stmt = select(Task).where(
            and_(
                Task.completed_at.is_not(None),
                Task.completed_at >= since,
                Task.rework_round > 0,
            ),
        )
        result = await self.session.execute(stmt)
        tasks = result.scalars().all()

        signals: list[dict[str, Any]] = []
        for task in tasks:
            if not task.assigned_agent_id:
                continue

            existing = await self._check_existing_signal(
                task_id=str(task.id),
                agent_id=task.assigned_agent_id,
                signal_type="rework",
            )
            if existing:
                continue

            if task.status == "failed":
                signal_value = 0.0
            elif task.rework_round == 0:
                signal_value = 1.0
            elif task.rework_round == 1:
                signal_value = 0.6
            else:
                signal_value = 0.3

            signal = await self.record_feedback(
                task_id=str(task.id),
                agent_id=task.assigned_agent_id,
                signal_type="rework",
                signal_value=signal_value,
                context={
                    "rework_rounds": task.rework_round,
                    "final_status": task.status,
                },
            )
            signals.append({
                "signal_id": signal.id,
                "agent_id": task.assigned_agent_id,
                "rework_rounds": task.rework_round,
            })

        logger.info("rework_signals_collected", count=len(signals))
        return signals

    async def _check_existing_signal(
        self,
        task_id: str,
        agent_id: str,
        signal_type: str,
    ) -> bool:
        """Check if a feedback signal already exists for this task/agent/type."""
        stmt = select(func.count()).select_from(FeedbackSignal).where(
            and_(
                FeedbackSignal.task_id == task_id,
                FeedbackSignal.agent_id == agent_id,
                FeedbackSignal.signal_type == signal_type,
            ),
        )
        result = await self.session.execute(stmt)
        count = result.scalar_one()
        return count > 0


class PreferenceUpdater:
    """Updates agent semantic memory with learned preferences from feedback.

    Analyzes feedback signals to derive preference patterns and writes them
    to semantic memory under the 'preferences.*' namespace. Agents load
    these preferences as context for future tasks.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def update_agent_preferences(
        self,
        agent_id: str,
        *,
        lookback_days: int = 30,
    ) -> dict[str, Any]:
        """Analyze feedback signals and update agent preferences in semantic memory.

        Args:
            agent_id: The agent to update preferences for.
            lookback_days: How far back to analyze signals.

        Returns:
            Summary of preference updates made.
        """
        since = datetime.now(UTC) - timedelta(days=lookback_days)

        # Get all signals for this agent
        stmt = select(FeedbackSignal).where(
            and_(
                FeedbackSignal.agent_id == agent_id,
                FeedbackSignal.created_at >= since,
            ),
        )
        result = await self.session.execute(stmt)
        signals = result.scalars().all()

        if not signals:
            return {"agent_id": agent_id, "updates": 0, "message": "No feedback signals found"}

        # Compute approval rate
        approval_signals = [s for s in signals if s.signal_type == "approval"]
        if approval_signals:
            approval_rate = sum(s.signal_value for s in approval_signals) / len(approval_signals)
            await self._upsert_preference(
                agent_id=agent_id,
                key="approval_rate",
                value=f"Approval rate: {approval_rate:.0%} over {len(approval_signals)} actions. "
                f"{'Users generally approve your actions.' if approval_rate > 0.7 else 'Users frequently reject your actions — be more cautious.'}",
                confidence=min(len(approval_signals) / 20, 1.0),
            )

        # Compute rework rate
        rework_signals = [s for s in signals if s.signal_type == "rework"]
        if rework_signals:
            avg_quality = sum(s.signal_value for s in rework_signals) / len(rework_signals)
            await self._upsert_preference(
                agent_id=agent_id,
                key="rework_quality",
                value=f"QA quality score: {avg_quality:.0%} over {len(rework_signals)} reviewed tasks. "
                f"{'Your outputs rarely need rework.' if avg_quality > 0.7 else 'Your outputs frequently require rework — improve thoroughness.'}",
                confidence=min(len(rework_signals) / 10, 1.0),
            )

        # Compute rating average
        rating_signals = [s for s in signals if s.signal_type == "rating"]
        if rating_signals:
            avg_rating = sum(s.signal_value for s in rating_signals) / len(rating_signals)
            await self._upsert_preference(
                agent_id=agent_id,
                key="user_satisfaction",
                value=f"User satisfaction: {avg_rating:.0%} over {len(rating_signals)} ratings. "
                f"{'Users are satisfied with your work.' if avg_rating > 0.7 else 'Users are dissatisfied — adjust your approach.'}",
                confidence=min(len(rating_signals) / 10, 1.0),
            )

        # Analyze tool-specific patterns from rejected approvals
        rejected = [
            s for s in approval_signals
            if s.signal_value == 0.0 and s.context.get("tool_name")
        ]
        if rejected:
            tool_rejections: dict[str, int] = {}
            for s in rejected:
                tool = s.context["tool_name"]
                tool_rejections[tool] = tool_rejections.get(tool, 0) + 1

            for tool_name, count in tool_rejections.items():
                await self._upsert_preference(
                    agent_id=agent_id,
                    key=f"tool_caution_{tool_name}",
                    value=f"Tool '{tool_name}' has been rejected {count} times. "
                    f"Be extra careful when using this tool and provide detailed justification.",
                    confidence=min(count / 5, 1.0),
                )

        total_updates = len(approval_signals) + len(rework_signals) + len(rating_signals)
        logger.info(
            "preferences_updated",
            agent_id=agent_id,
            total_signals=len(signals),
            updates=total_updates,
        )
        return {
            "agent_id": agent_id,
            "total_signals": len(signals),
            "approval_signals": len(approval_signals),
            "rework_signals": len(rework_signals),
            "rating_signals": len(rating_signals),
        }

    async def _upsert_preference(
        self,
        agent_id: str,
        key: str,
        value: str,
        confidence: float,
    ) -> None:
        """Upsert a preference into semantic memory."""
        namespace = "preferences.feedback"
        stmt = select(SemanticMemory).where(
            and_(
                SemanticMemory.agent_id == agent_id,
                SemanticMemory.namespace == namespace,
                SemanticMemory.key == key,
            ),
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.value = value
            existing.confidence = confidence
            existing.updated_at = datetime.now(UTC)
        else:
            memory = SemanticMemory(
                id=str(uuid4()),
                agent_id=agent_id,
                namespace=namespace,
                key=key,
                value=value,
                confidence=confidence,
            )
            self.session.add(memory)
        await self.session.flush()


async def get_agent_feedback_stats(
    session: AsyncSession,
    agent_id: str,
    *,
    lookback_days: int = 30,
) -> dict[str, Any]:
    """Get feedback statistics for an agent (used by dashboard).

    Args:
        session: Database session.
        agent_id: Agent to get stats for.
        lookback_days: How far back to look.

    Returns:
        Feedback statistics summary.
    """
    since = datetime.now(UTC) - timedelta(days=lookback_days)
    stmt = select(FeedbackSignal).where(
        and_(
            FeedbackSignal.agent_id == agent_id,
            FeedbackSignal.created_at >= since,
        ),
    )
    result = await session.execute(stmt)
    signals = result.scalars().all()

    stats: dict[str, Any] = {
        "agent_id": agent_id,
        "total_signals": len(signals),
        "by_type": {},
    }

    for signal_type in ("approval", "rating", "rework", "escalation"):
        typed = [s for s in signals if s.signal_type == signal_type]
        if typed:
            stats["by_type"][signal_type] = {
                "count": len(typed),
                "avg_value": sum(s.signal_value for s in typed) / len(typed),
                "positive": sum(1 for s in typed if s.signal_value >= 0.5),
                "negative": sum(1 for s in typed if s.signal_value < 0.5),
            }

    return stats
