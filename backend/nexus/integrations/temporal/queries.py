"""Temporal query definitions for real-time task status.

Queries allow the dashboard to poll workflow state without
interrupting execution. Returns current status, progress,
and subtask completion counts.
"""

from __future__ import annotations

import structlog

from nexus.integrations.temporal.schemas import TaskStatusQuery

logger = structlog.get_logger()


async def query_task_status(task_id: str) -> TaskStatusQuery:
    """Query the current status of a task workflow.

    First tries Temporal (if available), then falls back to
    database-based status lookup.

    Args:
        task_id: The task to query.

    Returns:
        TaskStatusQuery with current status and progress.
    """
    # Try database lookup (always available)
    try:
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from nexus.db.models import Task
        from nexus.settings import settings

        engine = create_async_engine(settings.database_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with session_factory() as session:
            # Get main task
            stmt = select(Task).where(Task.id == task_id)
            result = await session.execute(stmt)
            task = result.scalar_one_or_none()

            if not task:
                return TaskStatusQuery(
                    task_id=task_id,
                    status="not_found",
                )

            # Count subtasks
            subtask_count = await session.execute(
                select(func.count(Task.id)).where(Task.parent_task_id == task_id)
            )
            total_subtasks = subtask_count.scalar() or 0

            completed_count = await session.execute(
                select(func.count(Task.id)).where(
                    Task.parent_task_id == task_id,
                    Task.status == "completed",
                )
            )
            completed_subtasks = completed_count.scalar() or 0

            # Calculate progress
            if task.status == "completed":
                progress = 100
            elif task.status == "failed":
                progress = 0
            elif total_subtasks > 0:
                progress = int((completed_subtasks / total_subtasks) * 80) + 10
            else:
                progress = 10

            # Determine current step
            status_map = {
                "queued": "planning",
                "running": "executing",
                "paused": "waiting",
                "awaiting_approval": "reviewing",
                "completed": "completed",
                "failed": "failed",
            }

            elapsed = 0
            if task.started_at and task.created_at:
                elapsed = int((task.started_at - task.created_at).total_seconds())

            await engine.dispose()

            return TaskStatusQuery(
                task_id=task_id,
                status=status_map.get(task.status, task.status),
                current_step=status_map.get(task.status, "unknown"),
                progress_pct=progress,
                subtasks_total=total_subtasks,
                subtasks_completed=completed_subtasks,
                elapsed_seconds=elapsed,
                waiting_for_approval=task.status == "awaiting_approval",
            )

    except Exception as exc:
        logger.error("query_task_status_failed", task_id=task_id, error=str(exc))
        return TaskStatusQuery(
            task_id=task_id,
            status="error",
            current_step=f"Query failed: {exc}",
        )
