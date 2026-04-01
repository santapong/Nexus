"""Temporal saga compensation logic.

Implements the saga pattern for multi-agent workflows:
when a subtask fails, compensating actions cancel sibling
subtasks and clean up partial state.

This prevents resource waste and ensures consistent state
when part of a multi-agent workflow fails.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.db.models import Task
from nexus.settings import settings

logger = structlog.get_logger()


async def compensate_failed_subtasks(
    parent_task_id: str,
    failed_subtask_id: str,
    reason: str = "sibling_failed",
) -> int:
    """Cancel all pending/running sibling subtasks when one fails.

    Implements the saga compensation pattern: if one subtask in a
    parallel fan-out fails, cancel the rest to avoid wasting resources.

    Args:
        parent_task_id: The parent task that spawned the subtasks.
        failed_subtask_id: The subtask that failed (won't be cancelled).
        reason: Cancellation reason for audit trail.

    Returns:
        Number of subtasks cancelled.
    """
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            # Find all sibling subtasks that are still running or queued
            stmt = (
                update(Task)
                .where(
                    Task.parent_task_id == parent_task_id,
                    Task.id != failed_subtask_id,
                    Task.status.in_(["queued", "running"]),
                )
                .values(
                    status="failed",
                    error=f"Cancelled: {reason} (sibling {failed_subtask_id} failed)",
                )
                .returning(Task.id)
            )
            result = await session.execute(stmt)
            cancelled_ids = result.scalars().all()
            await session.commit()

            if cancelled_ids:
                logger.info(
                    "saga_compensation_executed",
                    parent_task_id=parent_task_id,
                    failed_subtask_id=failed_subtask_id,
                    cancelled_count=len(cancelled_ids),
                    cancelled_ids=[str(id) for id in cancelled_ids],
                )

            return len(cancelled_ids)

    except Exception as exc:
        logger.error(
            "saga_compensation_failed",
            parent_task_id=parent_task_id,
            error=str(exc),
        )
        return 0
    finally:
        await engine.dispose()


async def cleanup_orphaned_subtasks(
    parent_task_id: str,
    max_age_seconds: int = 3600,
) -> int:
    """Clean up subtasks that are stuck in running state.

    Called during crash recovery — finds subtasks whose parent task
    has completed/failed but the subtasks themselves are still "running".

    Args:
        parent_task_id: The parent task ID.
        max_age_seconds: Maximum age before a running subtask is considered orphaned.

    Returns:
        Number of orphaned subtasks cleaned up.
    """
    from datetime import datetime, timedelta, timezone

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)

            stmt = (
                update(Task)
                .where(
                    Task.parent_task_id == parent_task_id,
                    Task.status == "running",
                    Task.started_at < cutoff,
                )
                .values(
                    status="failed",
                    error="Orphaned subtask — cleaned up by saga recovery",
                )
                .returning(Task.id)
            )
            result = await session.execute(stmt)
            orphaned_ids = result.scalars().all()
            await session.commit()

            if orphaned_ids:
                logger.info(
                    "orphaned_subtasks_cleaned",
                    parent_task_id=parent_task_id,
                    count=len(orphaned_ids),
                )

            return len(orphaned_ids)

    except Exception as exc:
        logger.error(
            "orphan_cleanup_failed",
            parent_task_id=parent_task_id,
            error=str(exc),
        )
        return 0
    finally:
        await engine.dispose()
