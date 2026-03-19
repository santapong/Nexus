"""Scheduled tasks API — CRUD for recurring task schedules.

Allows users to create, list, update, and deactivate cron-based
task schedules that automatically create tasks at specified intervals.
"""

from __future__ import annotations

from typing import Any

import structlog
from litestar import Controller, delete, get, patch, post
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import TaskSchedule

logger = structlog.get_logger()


# ─── Request/Response Models ─────────────────────────────────────────────────


class CreateScheduleRequest(BaseModel):
    """Request body for creating a task schedule."""

    name: str = Field(..., max_length=200)
    cron_expression: str = Field(..., max_length=100)
    instruction: str = Field(..., max_length=10000)
    target_role: str = Field(..., max_length=50)
    workspace_id: str
    timezone: str = "UTC"
    max_runs: int | None = None
    metadata: dict[str, Any] | None = None


class UpdateScheduleRequest(BaseModel):
    """Request body for updating a task schedule."""

    name: str | None = None
    cron_expression: str | None = None
    instruction: str | None = None
    is_active: bool | None = None
    max_runs: int | None = None


class ScheduleResponse(BaseModel):
    """Response for a single task schedule."""

    id: str
    name: str
    cron_expression: str
    instruction: str
    target_role: str
    workspace_id: str
    is_active: bool
    timezone: str
    last_run_at: str | None
    next_run_at: str | None
    total_runs: int
    max_runs: int | None


class ScheduleListResponse(BaseModel):
    """Response for listing task schedules."""

    schedules: list[ScheduleResponse]
    total: int


def _to_response(schedule: TaskSchedule) -> ScheduleResponse:
    return ScheduleResponse(
        id=str(schedule.id),
        name=schedule.name,
        cron_expression=schedule.cron_expression,
        instruction=schedule.instruction[:500],
        target_role=schedule.target_role,
        workspace_id=str(schedule.workspace_id),
        is_active=schedule.is_active,
        timezone=schedule.timezone,
        last_run_at=schedule.last_run_at.isoformat() if schedule.last_run_at else None,
        next_run_at=schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        total_runs=schedule.total_runs,
        max_runs=schedule.max_runs,
    )


# ─── Controller ──────────────────────────────────────────────────────────────


class ScheduleController(Controller):
    """CRUD endpoints for task schedules."""

    path = "/schedules"

    @post("/")
    async def create_schedule(
        self,
        data: CreateScheduleRequest,
        db_session: AsyncSession,
    ) -> ScheduleResponse:
        """Create a new task schedule.

        Validates the cron expression and calculates the first next_run_at.
        """
        from nexus.core.scheduler import create_schedule

        schedule = await create_schedule(
            session=db_session,
            workspace_id=data.workspace_id,
            name=data.name,
            cron_expression=data.cron_expression,
            instruction=data.instruction,
            target_role=data.target_role,
            timezone=data.timezone,
            max_runs=data.max_runs,
            metadata=data.metadata,
        )
        await db_session.commit()
        return _to_response(schedule)

    @get("/")
    async def list_schedules(
        self,
        db_session: AsyncSession,
        workspace_id: str | None = None,
        active_only: bool = True,
    ) -> ScheduleListResponse:
        """List task schedules, optionally filtered by workspace."""
        stmt = select(TaskSchedule).order_by(TaskSchedule.created_at.desc())

        if workspace_id:
            stmt = stmt.where(TaskSchedule.workspace_id == workspace_id)
        if active_only:
            stmt = stmt.where(TaskSchedule.is_active.is_(True))

        result = await db_session.execute(stmt)
        schedules = result.scalars().all()

        return ScheduleListResponse(
            schedules=[_to_response(s) for s in schedules],
            total=len(schedules),
        )

    @get("/{schedule_id:str}")
    async def get_schedule(
        self,
        schedule_id: str,
        db_session: AsyncSession,
    ) -> ScheduleResponse | dict[str, str]:
        """Get a single task schedule by ID."""
        stmt = select(TaskSchedule).where(TaskSchedule.id == schedule_id)
        result = await db_session.execute(stmt)
        schedule = result.scalar_one_or_none()

        if schedule is None:
            return {"error": f"Schedule {schedule_id} not found"}

        return _to_response(schedule)

    @patch("/{schedule_id:str}")
    async def update_schedule(
        self,
        schedule_id: str,
        data: UpdateScheduleRequest,
        db_session: AsyncSession,
    ) -> ScheduleResponse | dict[str, str]:
        """Update a task schedule."""
        stmt = select(TaskSchedule).where(TaskSchedule.id == schedule_id)
        result = await db_session.execute(stmt)
        schedule = result.scalar_one_or_none()

        if schedule is None:
            return {"error": f"Schedule {schedule_id} not found"}

        if data.name is not None:
            schedule.name = data.name
        if data.instruction is not None:
            schedule.instruction = data.instruction
        if data.is_active is not None:
            schedule.is_active = data.is_active
        if data.max_runs is not None:
            schedule.max_runs = data.max_runs

        if data.cron_expression is not None:
            from croniter import croniter

            if not croniter.is_valid(data.cron_expression):
                return {"error": f"Invalid cron expression: {data.cron_expression}"}
            schedule.cron_expression = data.cron_expression
            # Recalculate next_run_at
            from nexus.core.scheduler import calculate_next_run

            schedule.next_run_at = calculate_next_run(data.cron_expression, schedule.timezone)

        await db_session.commit()
        logger.info("schedule_updated", schedule_id=schedule_id)
        return _to_response(schedule)

    @delete("/{schedule_id:str}")
    async def deactivate_schedule(
        self,
        schedule_id: str,
        db_session: AsyncSession,
    ) -> dict[str, str]:
        """Deactivate a task schedule (soft delete)."""
        stmt = select(TaskSchedule).where(TaskSchedule.id == schedule_id)
        result = await db_session.execute(stmt)
        schedule = result.scalar_one_or_none()

        if schedule is None:
            return {"error": f"Schedule {schedule_id} not found"}

        schedule.is_active = False
        await db_session.commit()
        logger.info("schedule_deactivated", schedule_id=schedule_id)
        return {"id": schedule_id, "deactivated": "true"}
