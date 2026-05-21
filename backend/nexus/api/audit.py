"""Audit log API endpoints.

Provides read-only access to the audit_log table for observability and action
tracking across all agents.

All queries are scoped to the caller's workspace_id (extracted from the JWT)
via a join through tasks.workspace_id, since audit_log itself does not carry
a workspace_id column. RLS provides a defense-in-depth layer at the SQL
level, but we still filter explicitly here because:
  1. RLS requires `SET LOCAL nexus.workspace_id` per session — if a session
     starts without that GUC, RLS would block everything. Explicit filters
     keep the query correct even if the GUC is absent.
  2. Explicit predicates let PostgreSQL use indexes on tasks.workspace_id,
     turning a scan of the full audit_log into a tenant-scoped scan.
  3. Defense-in-depth: a bug in RLS policy setup should not be the only
     thing standing between tenant A and tenant B's audit logs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from litestar import Controller, Request, get
from litestar.exceptions import NotAuthorizedException
from litestar.params import Parameter
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.auth import require_auth_user
from nexus.db.models import AuditLog, Task

# Pagination hard cap — protects against `?limit=10000` enumeration attacks.
_MAX_LIMIT = 100


def _require_workspace_id(request: Request[Any, Any, Any]) -> str:
    """Require an authenticated workspace_id from the request JWT.

    Audit data must never be served to anonymous callers — without a workspace
    filter every event across every tenant would be visible. Raises 401 if the
    request lacks a valid Bearer token, or if the token has no workspace_id
    claim.

    Args:
        request: Litestar request object.

    Returns:
        The authenticated user's workspace_id (guaranteed non-empty).

    Raises:
        NotAuthorizedException: If no valid JWT is present or it has no
            workspace_id claim.
    """
    workspace_id = require_auth_user(request).workspace_id
    if not workspace_id:
        raise NotAuthorizedException(detail="No workspace associated with this user")
    return workspace_id


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
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
        agent_id: str | None = Parameter(query="agent_id", default=None),
        task_id: str | None = Parameter(query="task_id", default=None),
        event_type: str | None = Parameter(query="event_type", default=None),
        since: str | None = Parameter(query="since", default=None),
        limit: int = Parameter(query="limit", default=50, ge=1, le=_MAX_LIMIT),
        offset: int = Parameter(query="offset", default=0, ge=0),
    ) -> AuditListResponse:
        """List audit events with optional filters, scoped to workspace.

        Args:
            request: Litestar request (workspace_id source).
            db_session: Database session.
            agent_id: Filter by agent identifier.
            task_id: Filter by task UUID.
            event_type: Filter by event type (e.g. 'task_completed').
            since: ISO datetime string — only events after this time.
            limit: Max results per page (default 50, max 100).
            offset: Pagination offset.

        Returns:
            Paginated list of audit events belonging to the caller's workspace.
        """
        workspace_id = _require_workspace_id(request)

        # Build predicate list — used for both the SELECT and the COUNT, so
        # they stay in sync. NOTE: workspace_id filter required even with RLS
        # — see module docstring.
        predicates: list[Any] = [Task.workspace_id == workspace_id]
        if agent_id:
            predicates.append(AuditLog.agent_id == agent_id)
        if task_id:
            predicates.append(AuditLog.task_id == task_id)
        if event_type:
            predicates.append(AuditLog.event_type == event_type)
        if since:
            try:
                since_dt = datetime.fromisoformat(since)
                predicates.append(AuditLog.created_at >= since_dt)
            except ValueError:
                pass  # Ignore invalid date — return unfiltered by date

        # Count total matching — direct COUNT against the joined predicate set
        # rather than wrapping a paginated subquery (which would materialize
        # the entire page just to count it).
        count_stmt = (
            select(func.count(AuditLog.id))
            .select_from(AuditLog)
            .join(Task, Task.id == AuditLog.task_id)
            .where(*predicates)
        )
        total = (await db_session.execute(count_stmt)).scalar() or 0

        # Fetch the paginated rows.
        stmt = (
            select(AuditLog)
            .join(Task, Task.id == AuditLog.task_id)
            .where(*predicates)
            .order_by(AuditLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
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
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
        limit: int = Parameter(query="limit", default=_MAX_LIMIT, ge=1, le=_MAX_LIMIT),
    ) -> list[AuditEventResponse]:
        """Get the full audit timeline for a specific task, scoped to workspace.

        Args:
            task_id: Task UUID string.
            request: Litestar request (workspace_id source).
            db_session: Database session.
            limit: Max events to return (default 100, max 100).

        Returns:
            Chronologically ordered list of audit events for the task, or an
            empty list if the task does not belong to the caller's workspace.
        """
        workspace_id = _require_workspace_id(request)

        # Join through tasks so a caller cannot read events for a task they
        # don't own. NOTE: workspace_id filter required even with RLS — see
        # module docstring.
        stmt = (
            select(AuditLog)
            .join(Task, Task.id == AuditLog.task_id)
            .where(
                AuditLog.task_id == task_id,
                Task.workspace_id == workspace_id,
            )
            .order_by(AuditLog.created_at.asc())
            .limit(limit)
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
