"""Task feedback API — human ratings for completed tasks (Phase 9 Track 1).

Users submit a dual-score feedback per task:
- helpful_score: 1–5 (was the output useful?)
- safe_score: 1–5 (was the output safe, in-scope, non-toxic?)
- optional comment

Each submission writes two rows into the existing `feedback_signals` table
(one per dimension, normalized to 0.0–1.0) plus a preference record into
`semantic_memory` via the canonical `upsert_fact()` writer. This is the
foundation for BACKLOG-051 (RLHF-lite) and BACKLOG-048 (fine-tuning dataset
export) — both read from `feedback_signals`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog
from litestar import Controller, Request, get, post
from litestar.exceptions import NotFoundException, ValidationException
from litestar.params import Parameter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.auth import get_auth_user_from_request
from nexus.db.models import FeedbackSignal, Task
from nexus.memory.semantic import upsert_fact

logger = structlog.get_logger()


# ─── Request/Response Models ─────────────────────────────────────


class SubmitFeedbackRequest(BaseModel):
    """Dual-score feedback on a completed task."""

    helpful_score: int = Field(ge=1, le=5)
    safe_score: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2_000)


class FeedbackSignalRecord(BaseModel):
    id: str
    task_id: str
    agent_id: str
    signal_type: str  # 'helpful' | 'safe' | legacy types
    signal_value: float  # 0.0–1.0
    context: dict[str, Any]
    created_at: str


class SubmitFeedbackResponse(BaseModel):
    task_id: str
    submitted: bool
    signals_written: int
    preference_recorded: bool


# ─── Helpers ────────────────────────────────────────────────────


def _get_workspace_id(request: Request[Any, Any, Any]) -> str | None:
    auth_user = get_auth_user_from_request(request)
    return auth_user.workspace_id if auth_user is not None else None


def _signal_row(
    *,
    task_id: str,
    agent_id: str,
    signal_type: str,
    raw_score: int,
    context: dict[str, Any],
) -> FeedbackSignal:
    """Build one FeedbackSignal row from a 1–5 raw score."""
    return FeedbackSignal(
        id=str(uuid4()),
        task_id=task_id,
        agent_id=agent_id,
        signal_type=signal_type,
        signal_value=round(raw_score / 5.0, 3),
        context=context,
        created_at=datetime.now(UTC),
    )


# ─── Controller ─────────────────────────────────────────────────


class FeedbackController(Controller):
    """User-submitted task feedback. Feeds the RLHF-lite learning loop."""

    path = "/feedback"

    @post("/tasks/{task_id:str}")
    async def submit(
        self,
        task_id: str,
        data: SubmitFeedbackRequest,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
    ) -> SubmitFeedbackResponse:
        """Submit dual-score feedback for a completed task.

        Writes two rows into `feedback_signals` (helpful + safe) and, when
        the task has an assigned agent, an aggregated preference record into
        `semantic_memory` via `upsert_fact()`.
        """
        workspace_id = _get_workspace_id(request)
        auth_user = get_auth_user_from_request(request)
        user_id = auth_user.user_id if auth_user is not None else None

        # Workspace-scoped task lookup — returns 404 if task is in another workspace
        stmt = select(Task).where(Task.id == task_id)
        if workspace_id:
            stmt = stmt.where(Task.workspace_id == workspace_id)
        task = (await db_session.execute(stmt)).scalar_one_or_none()
        if task is None:
            raise NotFoundException(detail=f"Task {task_id} not found")

        if task.assigned_agent_id is None:
            # No agent to attribute feedback to — feedback_signals.agent_id is NOT NULL.
            raise ValidationException(
                detail="Task has no assigned agent; cannot record feedback."
            )

        context: dict[str, Any] = {
            "submitted_by": user_id,
            "workspace_id": workspace_id,
            "comment": data.comment,
            "raw_helpful": data.helpful_score,
            "raw_safe": data.safe_score,
        }

        db_session.add(
            _signal_row(
                task_id=task_id,
                agent_id=task.assigned_agent_id,
                signal_type="helpful",
                raw_score=data.helpful_score,
                context=context,
            )
        )
        db_session.add(
            _signal_row(
                task_id=task_id,
                agent_id=task.assigned_agent_id,
                signal_type="safe",
                raw_score=data.safe_score,
                context=context,
            )
        )

        # Preference record in semantic memory (newest-wins per (agent, ns, key))
        preference_recorded = False
        try:
            await upsert_fact(
                session=db_session,
                agent_id=task.assigned_agent_id,
                namespace="feedback",
                key=f"task_{task_id}",
                value=json.dumps(
                    {
                        "helpful": round(data.helpful_score / 5.0, 3),
                        "safe": round(data.safe_score / 5.0, 3),
                        "comment": data.comment,
                    }
                ),
                confidence=1.0,
                source_task_id=task_id,
            )
            preference_recorded = True
        except Exception as exc:  # noqa: BLE001 — feedback must not fail on memory write
            logger.warning(
                "feedback_semantic_memory_failed",
                task_id=task_id,
                agent_id=task.assigned_agent_id,
                error=str(exc),
            )

        await db_session.commit()

        logger.info(
            "task_feedback_submitted",
            task_id=task_id,
            agent_id=task.assigned_agent_id,
            helpful=data.helpful_score,
            safe=data.safe_score,
            user_id=user_id,
        )

        return SubmitFeedbackResponse(
            task_id=task_id,
            submitted=True,
            signals_written=2,
            preference_recorded=preference_recorded,
        )

    @get("/tasks/{task_id:str}")
    async def list_for_task(
        self,
        task_id: str,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
    ) -> list[FeedbackSignalRecord]:
        """List feedback signals for a task, scoped to the caller's workspace."""
        workspace_id = _get_workspace_id(request)

        # Verify task belongs to workspace before exposing its feedback
        task_stmt = select(Task).where(Task.id == task_id)
        if workspace_id:
            task_stmt = task_stmt.where(Task.workspace_id == workspace_id)
        task = (await db_session.execute(task_stmt)).scalar_one_or_none()
        if task is None:
            raise NotFoundException(detail=f"Task {task_id} not found")

        stmt = (
            select(FeedbackSignal)
            .where(FeedbackSignal.task_id == task_id)
            .order_by(FeedbackSignal.created_at.desc())
        )
        rows = (await db_session.execute(stmt)).scalars().all()
        return [
            FeedbackSignalRecord(
                id=str(r.id),
                task_id=str(r.task_id),
                agent_id=str(r.agent_id),
                signal_type=r.signal_type,
                signal_value=float(r.signal_value),
                context=dict(r.context or {}),
                created_at=str(r.created_at),
            )
            for r in rows
        ]

    @get("/recent")
    async def list_recent(
        self,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
        limit: int = Parameter(query="limit", default=50, ge=1, le=200),
    ) -> list[FeedbackSignalRecord]:
        """Recent feedback across the caller's workspace."""
        workspace_id = _get_workspace_id(request)

        stmt = (
            select(FeedbackSignal)
            .join(Task, Task.id == FeedbackSignal.task_id)
            .order_by(FeedbackSignal.created_at.desc())
            .limit(limit)
        )
        if workspace_id:
            stmt = stmt.where(Task.workspace_id == workspace_id)

        rows = (await db_session.execute(stmt)).scalars().all()
        return [
            FeedbackSignalRecord(
                id=str(r.id),
                task_id=str(r.task_id),
                agent_id=str(r.agent_id),
                signal_type=r.signal_type,
                signal_value=float(r.signal_value),
                context=dict(r.context or {}),
                created_at=str(r.created_at),
            )
            for r in rows
        ]
