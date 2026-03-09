"""Prompt management API endpoints.

Provides CRUD operations for agent prompts, including diff view
between active and proposed versions, and activation with approval.
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from litestar import Controller, get, post
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import Prompt
from nexus.kafka.producer import publish
from nexus.kafka.schemas import KafkaMessage
from nexus.kafka.topics import Topics

logger = structlog.get_logger()


class PromptResponse(BaseModel):
    """Response model for a single prompt."""

    id: str
    agent_role: str
    version: int
    content: str
    benchmark_score: float | None
    is_active: bool
    authored_by: str
    notes: str | None
    created_at: str
    approved_at: str | None


class PromptDiffResponse(BaseModel):
    """Response model for prompt diff (current vs proposed)."""

    current: PromptResponse | None
    proposed: PromptResponse
    diff_lines: list[str]


class TriggerImprovementRequest(BaseModel):
    """Request to manually trigger prompt improvement."""

    target_role: str


class PromptController(Controller):
    """API controller for prompt management."""

    path = "/prompts"

    @get()
    async def list_prompts(
        self,
        db_session: AsyncSession,
        role: str | None = None,
        active_only: bool = False,
    ) -> list[PromptResponse]:
        """List all prompts, optionally filtered by role.

        Args:
            db_session: Database session.
            role: Optional role filter.
            active_only: If True, only return active prompts.

        Returns:
            List of prompts.
        """
        stmt = select(Prompt).order_by(
            Prompt.agent_role, Prompt.version.desc()
        )
        if role:
            stmt = stmt.where(Prompt.agent_role == role)
        if active_only:
            stmt = stmt.where(Prompt.is_active.is_(True))

        result = await db_session.execute(stmt)
        prompts = result.scalars().all()

        return [_to_response(p) for p in prompts]

    @get("/{prompt_id:str}/diff")
    async def get_prompt_diff(
        self,
        prompt_id: str,
        db_session: AsyncSession,
    ) -> PromptDiffResponse | dict[str, str]:
        """Get diff between the proposed prompt and its current active version.

        Args:
            prompt_id: The proposed prompt ID.
            db_session: Database session.

        Returns:
            PromptDiffResponse with current, proposed, and diff lines.
        """
        # Get the proposed prompt
        stmt = select(Prompt).where(Prompt.id == prompt_id)
        result = await db_session.execute(stmt)
        proposed = result.scalar_one_or_none()

        if proposed is None:
            return {"error": "Prompt not found"}

        # Get current active prompt for the same role
        active_stmt = (
            select(Prompt)
            .where(
                Prompt.agent_role == proposed.agent_role,
                Prompt.is_active.is_(True),
            )
            .order_by(Prompt.version.desc())
            .limit(1)
        )
        active_result = await db_session.execute(active_stmt)
        current = active_result.scalar_one_or_none()

        # Calculate simple line-by-line diff
        current_lines = current.content.splitlines() if current else []
        proposed_lines = proposed.content.splitlines()
        diff_lines = _simple_diff(current_lines, proposed_lines)

        return PromptDiffResponse(
            current=_to_response(current) if current else None,
            proposed=_to_response(proposed),
            diff_lines=diff_lines,
        )

    @post("/{prompt_id:str}/activate")
    async def activate_prompt(
        self,
        prompt_id: str,
        db_session: AsyncSession,
    ) -> dict[str, str]:
        """Activate a proposed prompt (deactivates the current one).

        This is the approval step — only called after human review.

        Args:
            prompt_id: The prompt ID to activate.
            db_session: Database session.

        Returns:
            Status message.
        """
        # Get the prompt
        stmt = select(Prompt).where(Prompt.id == prompt_id)
        result = await db_session.execute(stmt)
        prompt = result.scalar_one_or_none()

        if prompt is None:
            return {"error": "Prompt not found"}

        if prompt.is_active:
            return {"error": "Prompt is already active"}

        # Deactivate current active prompt for this role
        deactivate_stmt = (
            select(Prompt)
            .where(
                Prompt.agent_role == prompt.agent_role,
                Prompt.is_active.is_(True),
            )
        )
        deactivate_result = await db_session.execute(deactivate_stmt)
        for old_prompt in deactivate_result.scalars().all():
            old_prompt.is_active = False

        # Activate the new prompt
        prompt.is_active = True
        prompt.approved_at = datetime.now(timezone.utc)

        await db_session.commit()

        logger.info(
            "prompt_activated",
            prompt_id=prompt_id,
            role=prompt.agent_role,
            version=prompt.version,
        )

        return {
            "status": "activated",
            "prompt_id": prompt_id,
            "role": prompt.agent_role,
            "version": str(prompt.version),
        }

    @post("/improve")
    async def trigger_improvement(
        self,
        data: TriggerImprovementRequest,
        db_session: AsyncSession,
    ) -> dict[str, str]:
        """Manually trigger prompt improvement for a role.

        Publishes an improvement request to the prompt.improvement_requests
        topic, which the Prompt Creator Agent will consume.

        Args:
            data: Request with target_role.
            db_session: Database session.

        Returns:
            Status message.
        """
        from uuid import uuid4

        task_id = uuid4()
        trace_id = uuid4()

        msg = KafkaMessage(
            task_id=task_id,
            trace_id=trace_id,
            agent_id="api",
            payload={
                "target_role": data.target_role,
                "trigger": "manual",
            },
        )
        await publish(
            Topics.PROMPT_IMPROVEMENT, msg, key=str(task_id)
        )

        logger.info(
            "prompt_improvement_triggered",
            target_role=data.target_role,
            trigger="manual",
        )

        return {
            "status": "triggered",
            "target_role": data.target_role,
            "task_id": str(task_id),
        }


def _to_response(prompt: Prompt) -> PromptResponse:
    """Convert a Prompt model to a PromptResponse.

    Args:
        prompt: The Prompt model instance.

    Returns:
        PromptResponse.
    """
    return PromptResponse(
        id=str(prompt.id),
        agent_role=prompt.agent_role,
        version=prompt.version,
        content=prompt.content,
        benchmark_score=prompt.benchmark_score,
        is_active=prompt.is_active,
        authored_by=prompt.authored_by,
        notes=prompt.notes,
        created_at=str(prompt.created_at),
        approved_at=str(prompt.approved_at) if prompt.approved_at else None,
    )


def _simple_diff(
    old_lines: list[str], new_lines: list[str]
) -> list[str]:
    """Produce a simple line-by-line diff.

    Args:
        old_lines: Lines from the current active prompt.
        new_lines: Lines from the proposed prompt.

    Returns:
        List of diff lines with +/- prefixes.
    """
    diff: list[str] = []
    old_set = set(old_lines)
    new_set = set(new_lines)

    for line in old_lines:
        if line not in new_set:
            diff.append(f"- {line}")

    for line in new_lines:
        if line not in old_set:
            diff.append(f"+ {line}")

    return diff
