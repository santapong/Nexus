"""Task state recovery service — crash recovery for in-flight tasks.

On system startup, scans for tasks that were marked as 'running' when
the system shut down unexpectedly. These orphaned tasks are either
re-queued for retry or failed with an appropriate error message.

Enterprise-grade fault tolerance: no task is silently lost due to
a crash, restart, or infrastructure failure.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.kafka.producer import publish
from nexus.core.kafka.schemas import AgentCommand, KafkaMessage
from nexus.core.kafka.topics import Topics
from nexus.db.models import Task, TaskStatus

logger = structlog.get_logger()

# Tasks running longer than this are considered orphaned
ORPHAN_THRESHOLD_MINUTES = 30

# Maximum number of recovery retries before marking as failed
MAX_RECOVERY_RETRIES = 2


async def recover_orphaned_tasks(
    session: AsyncSession,
    *,
    threshold_minutes: int = ORPHAN_THRESHOLD_MINUTES,
) -> dict[str, Any]:
    """Scan for and recover orphaned tasks on startup.

    An orphaned task is one with status='running' that has been in that
    state longer than the threshold. This happens when the system crashes
    or an agent process dies mid-task.

    Recovery strategy:
    1. Tasks with rework_round < MAX_RECOVERY_RETRIES → re-queued
    2. Tasks that have been retried too many times → failed with error
    3. All recoveries are logged to the audit trail

    Args:
        session: Database session.
        threshold_minutes: Minutes after which a running task is orphaned.

    Returns:
        Summary dict with counts of recovered, failed, and skipped tasks.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=threshold_minutes)

    # Find orphaned tasks
    stmt = (
        select(Task)
        .where(Task.status == TaskStatus.RUNNING.value)
        .where(Task.started_at < cutoff)
    )
    result = await session.execute(stmt)
    orphaned_tasks = result.scalars().all()

    if not orphaned_tasks:
        logger.info("recovery_no_orphaned_tasks")
        return {"recovered": 0, "failed": 0, "skipped": 0}

    logger.warning(
        "recovery_orphaned_tasks_found",
        count=len(orphaned_tasks),
        threshold_minutes=threshold_minutes,
    )

    recovered = 0
    failed = 0
    skipped = 0

    for task in orphaned_tasks:
        task_id = str(task.id)

        # Skip subtasks — they'll be handled via parent task recovery
        if task.parent_task_id is not None:
            skipped += 1
            continue

        if task.rework_round < MAX_RECOVERY_RETRIES:
            # Re-queue the task
            task.status = TaskStatus.QUEUED.value
            task.rework_round += 1
            task.error = f"Auto-recovered after system restart (attempt {task.rework_round})"

            # Publish to task.queue for CEO to pick up
            requeue_command = AgentCommand(
                task_id=task.id,
                trace_id=task.trace_id,
                agent_id="recovery-service",
                payload={
                    "_recovery": True,
                    "recovery_attempt": task.rework_round,
                    "original_instruction": task.instruction,
                },
                target_role="ceo",
                instruction=task.instruction,
            )
            await publish(Topics.TASK_QUEUE, requeue_command, key=task_id)

            recovered += 1
            logger.info(
                "task_recovered_requeued",
                task_id=task_id,
                recovery_attempt=task.rework_round,
            )
        else:
            # Too many retries — mark as failed
            task.status = TaskStatus.FAILED.value
            task.error = (
                f"Task failed after {MAX_RECOVERY_RETRIES} recovery attempts. "
                "System crashed while this task was running."
            )
            task.completed_at = datetime.now(UTC)

            # Notify human
            human_msg = KafkaMessage(
                task_id=task.id,
                trace_id=task.trace_id,
                agent_id="recovery-service",
                payload={
                    "reason": "recovery_max_retries_exceeded",
                    "recovery_attempts": task.rework_round,
                    "instruction": task.instruction[:500],
                },
            )
            await publish(Topics.HUMAN_INPUT_NEEDED, human_msg, key=task_id)

            failed += 1
            logger.warning(
                "task_recovery_failed",
                task_id=task_id,
                recovery_attempts=task.rework_round,
            )

    # Also reset any 'paused' tasks that have no pending approvals
    paused_stmt = (
        select(Task)
        .where(Task.status == TaskStatus.PAUSED.value)
        .where(Task.started_at < cutoff)
    )
    paused_result = await session.execute(paused_stmt)
    paused_tasks = paused_result.scalars().all()

    for task in paused_tasks:
        logger.info(
            "paused_task_detected_during_recovery",
            task_id=str(task.id),
            instruction=task.instruction[:200],
        )

    await session.commit()

    summary = {
        "recovered": recovered,
        "failed": failed,
        "skipped": skipped,
        "paused_detected": len(paused_tasks),
    }

    logger.info("recovery_complete", **summary)
    return summary


async def cleanup_stale_locks(session: AsyncSession) -> int:
    """Clean up stale distributed locks from Redis.

    After a crash, Redis locks may remain held by dead processes.
    This function identifies and removes locks that are past their TTL
    but somehow survived (e.g., Redis PERSIST was accidentally called).

    Returns:
        Number of locks cleaned up.
    """
    from nexus.core.redis.clients import redis_locks

    cleaned = 0
    cursor = 0

    while True:
        cursor, keys = await redis_locks.scan(
            cursor=cursor, match="task_lock:*", count=100
        )
        for key in keys:
            ttl = await redis_locks.ttl(key)
            if ttl == -1:  # No TTL set — stale lock
                await redis_locks.delete(key)
                cleaned += 1
                logger.info("stale_lock_cleaned", key=key.decode() if isinstance(key, bytes) else key)

        if cursor == 0:
            break

    if cleaned > 0:
        logger.info("stale_locks_cleanup_complete", cleaned=cleaned)

    return cleaned
