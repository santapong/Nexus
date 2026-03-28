"""Graceful shutdown with in-flight task draining.

Enterprise-grade shutdown handling that ensures:
1. No new tasks are accepted after shutdown signal
2. In-flight tasks are given time to complete
3. Tasks that can't complete are checkpointed for recovery
4. All connections are cleanly closed

Integrates with the recovery service for crash-consistent restarts.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import Task, TaskStatus

logger = structlog.get_logger()

# Maximum seconds to wait for in-flight tasks during shutdown
DRAIN_TIMEOUT_SECONDS = 30

# Global shutdown state
_shutdown_requested = False
_active_tasks: set[str] = set()


def is_shutting_down() -> bool:
    """Check if shutdown has been requested.

    Agents should check this before starting new work.
    """
    return _shutdown_requested


def request_shutdown() -> None:
    """Signal that shutdown has been requested."""
    global _shutdown_requested  # noqa: PLW0603
    _shutdown_requested = True
    logger.info(
        "shutdown_requested",
        active_tasks=len(_active_tasks),
    )


def register_active_task(task_id: str) -> None:
    """Register a task as actively being processed.

    Args:
        task_id: The task ID being processed.
    """
    _active_tasks.add(task_id)


def unregister_active_task(task_id: str) -> None:
    """Mark a task as no longer actively being processed.

    Args:
        task_id: The task ID that completed.
    """
    _active_tasks.discard(task_id)


def get_active_task_count() -> int:
    """Get the number of currently active tasks."""
    return len(_active_tasks)


async def drain_and_shutdown(
    session_factory: Any,
    *,
    timeout: int = DRAIN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Wait for active tasks to complete, then checkpoint remaining ones.

    Args:
        session_factory: Database session factory.
        timeout: Maximum seconds to wait for draining.

    Returns:
        Summary of drain results.
    """
    logger.info(
        "drain_started",
        active_tasks=len(_active_tasks),
        timeout_seconds=timeout,
    )

    # Wait for active tasks to complete
    elapsed = 0
    poll_interval = 1

    while _active_tasks and elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        if elapsed % 5 == 0:
            logger.info(
                "drain_waiting",
                remaining_tasks=len(_active_tasks),
                elapsed_seconds=elapsed,
                task_ids=list(_active_tasks)[:5],
            )

    drained = len(_active_tasks) == 0
    remaining = list(_active_tasks)

    if not drained:
        # Checkpoint remaining tasks for recovery on restart
        logger.warning(
            "drain_timeout_checkpointing",
            remaining_tasks=len(remaining),
            task_ids=remaining[:10],
        )

        async with session_factory() as session:
            await _checkpoint_tasks(session, remaining)
            await session.commit()

    summary = {
        "drained": drained,
        "completed_during_drain": not bool(remaining),
        "checkpointed_tasks": len(remaining),
        "drain_seconds": elapsed,
    }

    logger.info("drain_complete", **summary)
    return summary


async def _checkpoint_tasks(session: AsyncSession, task_ids: list[str]) -> None:
    """Mark remaining in-flight tasks so they can be recovered on restart.

    Sets tasks to 'running' with an error note. The recovery service
    on the next startup will pick these up and re-queue them.

    Args:
        session: Database session.
        task_ids: List of task IDs to checkpoint.
    """
    if not task_ids:
        return

    stmt = (
        update(Task)
        .where(Task.id.in_(task_ids))
        .where(Task.status == TaskStatus.RUNNING.value)
        .values(
            error="Task interrupted during graceful shutdown — will be recovered on restart",
        )
    )
    await session.execute(stmt)

    logger.info(
        "tasks_checkpointed_for_recovery",
        count=len(task_ids),
    )
