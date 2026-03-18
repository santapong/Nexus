"""Prompt management API endpoints.

Provides CRUD operations for agent prompts, including diff view
between active and proposed versions, activation with approval,
version creation, and rollback.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import structlog
from litestar import Controller, get, post
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.audit.service import AuditEventType, log_event
from nexus.db.models import Agent, AuditLog, Prompt
from nexus.kafka.producer import publish
from nexus.kafka.schemas import KafkaMessage
from nexus.kafka.topics import Topics

logger = structlog.get_logger()


# ─── Request / Response Models ───────────────────────────────────────────────


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


class CreatePromptRequest(BaseModel):
    """Request to create a new prompt version."""

    agent_role: str
    content: str
    notes: str | None = None


class TriggerImprovementRequest(BaseModel):
    """Request to manually trigger prompt improvement."""

    target_role: str


class PromptHistoryEntry(BaseModel):
    """A single entry in the prompt activation history."""

    version: int
    activated_at: str
    event_type: str
    previous_version: int | None
    role: str


# ─── Controller ──────────────────────────────────────────────────────────────


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
        stmt = select(Prompt).order_by(Prompt.agent_role, Prompt.version.desc())
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

        current_lines = current.content.splitlines() if current else []
        proposed_lines = proposed.content.splitlines()
        diff_lines = _simple_diff(current_lines, proposed_lines)

        return PromptDiffResponse(
            current=_to_response(current) if current else None,
            proposed=_to_response(proposed),
            diff_lines=diff_lines,
        )

    @post("/create")
    async def create_prompt_version(
        self,
        data: CreatePromptRequest,
        db_session: AsyncSession,
    ) -> PromptResponse | dict[str, str]:
        """Create a new prompt version for a role.

        Auto-increments the version number. The new prompt is created
        as inactive — must be activated via /activate endpoint.

        Args:
            data: Request with agent_role, content, and optional notes.
            db_session: Database session.

        Returns:
            The newly created prompt.
        """
        # Get max version for this role
        max_ver_stmt = select(func.max(Prompt.version)).where(Prompt.agent_role == data.agent_role)
        max_ver_result = await db_session.execute(max_ver_stmt)
        max_version = max_ver_result.scalar() or 0

        new_prompt = Prompt(
            agent_role=data.agent_role,
            version=max_version + 1,
            content=data.content,
            is_active=False,
            authored_by="human",
            notes=data.notes,
        )
        db_session.add(new_prompt)
        await db_session.flush()

        # Audit: prompt_created
        await log_event(
            session=db_session,
            task_id=str(new_prompt.id),
            trace_id=str(new_prompt.id),
            agent_id="api",
            event_type=AuditEventType.PROMPT_CREATED,
            event_data={
                "role": data.agent_role,
                "version": max_version + 1,
            },
        )

        await db_session.commit()

        logger.info(
            "prompt_version_created",
            role=data.agent_role,
            version=max_version + 1,
        )

        return _to_response(new_prompt)

    @post("/{prompt_id:str}/activate")
    async def activate_prompt(
        self,
        prompt_id: str,
        db_session: AsyncSession,
    ) -> dict[str, str]:
        """Activate a proposed prompt (deactivates the current one).

        This is the approval step — only called after human review.
        Also syncs the agents table so running agents pick up the change.

        Args:
            prompt_id: The prompt ID to activate.
            db_session: Database session.

        Returns:
            Status message.
        """
        stmt = select(Prompt).where(Prompt.id == prompt_id)
        result = await db_session.execute(stmt)
        prompt = result.scalar_one_or_none()

        if prompt is None:
            return {"error": "Prompt not found"}

        if prompt.is_active:
            return {"error": "Prompt is already active"}

        # Find current active version for audit trail
        previous_version: int | None = None
        deactivate_stmt = select(Prompt).where(
            Prompt.agent_role == prompt.agent_role,
            Prompt.is_active.is_(True),
        )
        deactivate_result = await db_session.execute(deactivate_stmt)
        for old_prompt in deactivate_result.scalars().all():
            previous_version = old_prompt.version
            old_prompt.is_active = False

        # Activate the new prompt
        prompt.is_active = True
        prompt.approved_at = datetime.now(UTC)

        # Sync: update agents.system_prompt so running agents pick up the change
        await _sync_agent_prompt(db_session, prompt.agent_role, prompt.content)

        # Audit: prompt_activated
        await log_event(
            session=db_session,
            task_id=str(prompt.id),
            trace_id=str(prompt.id),
            agent_id="api",
            event_type=AuditEventType.PROMPT_ACTIVATED,
            event_data={
                "role": prompt.agent_role,
                "version": prompt.version,
                "previous_version": previous_version,
            },
        )

        await db_session.commit()

        logger.info(
            "prompt_activated",
            prompt_id=prompt_id,
            role=prompt.agent_role,
            version=prompt.version,
            previous_version=previous_version,
        )

        return {
            "status": "activated",
            "prompt_id": prompt_id,
            "role": prompt.agent_role,
            "version": str(prompt.version),
        }

    @post("/{prompt_id:str}/rollback")
    async def rollback_prompt(
        self,
        prompt_id: str,
        db_session: AsyncSession,
    ) -> dict[str, str | None]:
        """Rollback to a specific prompt version.

        Deactivates the current active prompt and activates the target.
        Syncs the agents table so running agents pick up the change.

        Args:
            prompt_id: The prompt ID to rollback to.
            db_session: Database session.

        Returns:
            Status message.
        """
        stmt = select(Prompt).where(Prompt.id == prompt_id)
        result = await db_session.execute(stmt)
        target = result.scalar_one_or_none()

        if target is None:
            return {"error": "Prompt not found"}

        # Find and deactivate current active prompt
        previous_version: int | None = None
        deactivate_stmt = select(Prompt).where(
            Prompt.agent_role == target.agent_role,
            Prompt.is_active.is_(True),
        )
        deactivate_result = await db_session.execute(deactivate_stmt)
        for old_prompt in deactivate_result.scalars().all():
            previous_version = old_prompt.version
            old_prompt.is_active = False

        # Activate target version
        target.is_active = True
        target.approved_at = datetime.now(UTC)

        # Sync agents table
        await _sync_agent_prompt(db_session, target.agent_role, target.content)

        # Audit: prompt_rollback
        await log_event(
            session=db_session,
            task_id=str(target.id),
            trace_id=str(target.id),
            agent_id="api",
            event_type=AuditEventType.PROMPT_ROLLBACK,
            event_data={
                "role": target.agent_role,
                "to_version": target.version,
                "from_version": previous_version,
            },
        )

        await db_session.commit()

        logger.info(
            "prompt_rollback",
            role=target.agent_role,
            to_version=target.version,
            from_version=previous_version,
        )

        return {
            "status": "rolled_back",
            "prompt_id": prompt_id,
            "role": target.agent_role,
            "version": str(target.version),
            "previous_version": str(previous_version) if previous_version else None,
        }

    @get("/history/{role:str}")
    async def get_prompt_history(
        self,
        role: str,
        db_session: AsyncSession,
    ) -> list[PromptHistoryEntry]:
        """Get the activation/rollback history for a role.

        Queries the audit_log for prompt_activated and prompt_rollback events.

        Args:
            role: Agent role to get history for.
            db_session: Database session.

        Returns:
            Chronologically ordered list of prompt activations and rollbacks.
        """
        stmt = (
            select(AuditLog)
            .where(
                AuditLog.event_type.in_(
                    [
                        AuditEventType.PROMPT_ACTIVATED.value,
                        AuditEventType.PROMPT_ROLLBACK.value,
                    ]
                ),
            )
            .order_by(AuditLog.created_at.desc())
            .limit(50)
        )
        result = await db_session.execute(stmt)
        events = result.scalars().all()

        # Filter by role from event_data (JSONB)
        history: list[PromptHistoryEntry] = []
        for event in events:
            data = event.event_data or {}
            if data.get("role") != role:
                continue
            history.append(
                PromptHistoryEntry(
                    version=data.get("version") or data.get("to_version", 0),
                    activated_at=str(event.created_at),
                    event_type=event.event_type,
                    previous_version=data.get("previous_version") or data.get("from_version"),
                    role=role,
                )
            )

        return history

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
        await publish(Topics.PROMPT_IMPROVEMENT, msg, key=str(task_id))

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


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def _sync_agent_prompt(
    session: AsyncSession,
    agent_role: str,
    content: str,
) -> None:
    """Update the agents table system_prompt for the given role.

    This ensures running agents pick up prompt changes on their next task
    via the hot-reload check in AgentBase._execute_with_guards.

    Args:
        session: Database session (caller manages commit).
        agent_role: Agent role to update.
        content: New system prompt content.
    """
    agent_stmt = select(Agent).where(Agent.role == agent_role)
    agent_result = await session.execute(agent_stmt)
    for agent_record in agent_result.scalars().all():
        agent_record.system_prompt = content


def _to_response(prompt: Prompt) -> PromptResponse:
    """Convert a Prompt model to a PromptResponse."""
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


def _simple_diff(old_lines: list[str], new_lines: list[str]) -> list[str]:
    """Produce a simple line-by-line diff."""
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
