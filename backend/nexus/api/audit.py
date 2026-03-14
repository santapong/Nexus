"""Audit log API endpoints.

Provides read-only access to the audit_log table for observability
and action tracking across all agents.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from litestar import Controller, get
from litestar.params import Parameter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import AuditLog


class AuditEventResponse(BaseModel):
    """Response model for a single audit event."""

    id: str
    task_id: str
    trace_id: str
    agent_id: str
    event_type: str
    event_data: dict[str, Any]
    created_at: str


class AuditListResponse(BaseModel):
    """Paginated list of audit events."""

    events: list[AuditEventResponse]
    total: int
    limit: int
    offset: int


class AuditController(Controller):
    """Read-only API for browsing the audit log."""

    path = "/audit"

    @get()
    async def list_events(
        self,
        db_session: AsyncSession,
        agent_id: str | None = Parameter(query="agent_id", default=None),
        task_id: str | None = Parameter(query="task_id", default=None),
        event_type: str | None = Parameter(query="event_type", default=None),
        since: str | None = Parameter(query="since", default=None),
        limit: int = Parameter(query="limit", default=50, le=200),
        offset: int = Parameter(query="offset", default=0),
    ) -> AuditListResponse:
        """List audit events with optional filters.

        Args:
            db_session: Database session.
            agent_id: Filter by agent identifier.
            task_id: Filter by task UUID.
            event_type: Filter by event type (e.g. 'task_completed').
            since: ISO datetime string — only events after this time.
            limit: Max results per page (default 50, max 200).
            offset: Pagination offset.

        Returns:
            Paginated list of audit events.
        """
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc())

        if agent_id:
            stmt = stmt.where(AuditLog.agent_id == agent_id)
        if task_id:
            stmt = stmt.where(AuditLog.task_id == task_id)
        if event_type:
            stmt = stmt.where(AuditLog.event_type == event_type)
        if since:
            try:
                since_dt = datetime.fromisoformat(since)
                stmt = stmt.where(AuditLog.created_at >= since_dt)
            except ValueError:
                pass  # Ignore invalid date — return unfiltered

        # Count total matching
        from sqlalchemy import func

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await db_session.execute(count_stmt)).scalar() or 0

        # Apply pagination
        stmt = stmt.offset(offset).limit(limit)
        result = await db_session.execute(stmt)
        events = result.scalars().all()

        return AuditListResponse(
            events=[_to_response(e) for e in events],
            total=total,
            limit=limit,
            offset=offset,
        )

    @get("/{task_id:str}/timeline")
    async def get_task_timeline(
        self,
        task_id: str,
        db_session: AsyncSession,
    ) -> list[AuditEventResponse]:
        """Get the full audit timeline for a specific task.

        Args:
            task_id: Task UUID string.
            db_session: Database session.

        Returns:
            Chronologically ordered list of all audit events for the task.
        """
        stmt = (
            select(AuditLog)
            .where(AuditLog.task_id == task_id)
            .order_by(AuditLog.created_at.asc())
        )
        result = await db_session.execute(stmt)
        events = result.scalars().all()

        return [_to_response(e) for e in events]


def _to_response(event: AuditLog) -> AuditEventResponse:
    """Convert AuditLog model to response."""
    return AuditEventResponse(
        id=str(event.id),
        task_id=str(event.task_id),
        trace_id=str(event.trace_id),
        agent_id=event.agent_id,
        event_type=event.event_type,
        event_data=event.event_data or {},
        created_at=str(event.created_at),
    )
