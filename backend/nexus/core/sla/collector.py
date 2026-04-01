"""SLA metrics collector — periodic snapshots of platform health.

Collects task throughput, queue wait times, error rates, and agent
availability every 5 minutes. Stores snapshots in sla_snapshots table
for rolling SLA compliance calculation.

Designed to run as an async background task via the scheduler.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import Agent as AgentModel
from nexus.db.models import SLASnapshot, Task

logger = structlog.get_logger()

# Collection window — how far back each snapshot looks
_WINDOW_MINUTES = 5


async def collect_sla_snapshot(
    session: AsyncSession,
    workspace_id: UUID | None = None,
) -> SLASnapshot:
    """Collect a single SLA metrics snapshot for the given workspace.

    Queries the tasks table for the last 5 minutes to compute:
    - Tasks queued and completed
    - Average queue wait time (created_at → started_at)
    - Error rate (failed / total)
    - Agent availability (active agents count)

    Args:
        session: Database session.
        workspace_id: Optional workspace filter. None = platform-wide.

    Returns:
        The created SLASnapshot record.
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=_WINDOW_MINUTES)

    # Base query for tasks in the window
    base_filter = Task.created_at >= window_start
    if workspace_id is not None:
        base_filter = base_filter & (Task.workspace_id == workspace_id)

    # Count tasks by status
    total_result = await session.execute(
        select(func.count(Task.id)).where(base_filter)
    )
    tasks_total = total_result.scalar() or 0

    completed_result = await session.execute(
        select(func.count(Task.id)).where(
            base_filter,
            Task.status == "completed",
        )
    )
    tasks_completed = completed_result.scalar() or 0

    failed_result = await session.execute(
        select(func.count(Task.id)).where(
            base_filter,
            Task.status == "failed",
        )
    )
    tasks_failed = failed_result.scalar() or 0

    # Average queue wait time (seconds between created_at and started_at)
    wait_result = await session.execute(
        select(
            func.avg(
                func.extract("epoch", Task.started_at) - func.extract("epoch", Task.created_at)
            )
        ).where(
            base_filter,
            Task.started_at.isnot(None),
        )
    )
    avg_wait_seconds = wait_result.scalar() or 0.0

    # Active agents count
    agents_result = await session.execute(
        select(func.count(AgentModel.id)).where(AgentModel.is_active.is_(True))
    )
    agents_available = agents_result.scalar() or 0

    # Error rate
    error_rate = (tasks_failed / tasks_total * 100.0) if tasks_total > 0 else 0.0

    # Uptime percentage — based on whether tasks are being processed
    # If tasks are queued but none are completing, uptime is degraded
    if tasks_total == 0:
        uptime_pct = 100.0  # No load = healthy
    elif tasks_completed > 0:
        uptime_pct = (tasks_completed / tasks_total) * 100.0
    else:
        uptime_pct = 0.0  # Tasks queued but none completed

    snapshot = SLASnapshot(
        workspace_id=workspace_id,
        timestamp=now,
        tasks_queued=tasks_total - tasks_completed - tasks_failed,
        tasks_completed=tasks_completed,
        avg_wait_seconds=round(avg_wait_seconds, 2),
        error_rate=round(error_rate, 2),
        agents_available=agents_available,
        uptime_pct=round(uptime_pct, 2),
    )

    session.add(snapshot)
    await session.flush()

    logger.info(
        "sla_snapshot_collected",
        workspace_id=str(workspace_id) if workspace_id else "platform",
        tasks_total=tasks_total,
        tasks_completed=tasks_completed,
        avg_wait_seconds=round(avg_wait_seconds, 2),
        error_rate=round(error_rate, 2),
        uptime_pct=round(uptime_pct, 2),
    )

    return snapshot
