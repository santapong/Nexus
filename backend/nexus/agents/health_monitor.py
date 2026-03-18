"""Health monitor — auto-fails tasks when agents go silent.

Consumes agent.heartbeat topic, tracks last heartbeat per agent in Redis,
and auto-fails tasks assigned to agents with no heartbeat in 5 minutes.

Run as part of the agent runner (see runner.py).
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.db.models import AuditLog, Task, TaskStatus
from nexus.integrations.kafka.consumer import create_consumer
from nexus.integrations.kafka.producer import publish
from nexus.integrations.kafka.schemas import AgentResponse
from nexus.integrations.kafka.topics import Topics
from nexus.integrations.redis.clients import redis_cache

logger = structlog.get_logger()

# ─── Constants ───────────────────────────────────────────────────────────────

HEARTBEAT_KEY_PREFIX = "heartbeat"
HEARTBEAT_TTL_SECONDS = 600  # 10 min TTL (cleanup buffer)
SILENCE_THRESHOLD_SECONDS = 300  # 5 minutes = considered dead
SCAN_INTERVAL_SECONDS = 60  # Check every 60 seconds


# ─── Heartbeat tracker ──────────────────────────────────────────────────────


async def _record_heartbeat(agent_id: str) -> None:
    """Record a heartbeat for an agent in Redis cache (db:1)."""
    key = f"{HEARTBEAT_KEY_PREFIX}:{agent_id}"
    now = time.time()
    await redis_cache.set(key, str(now), ex=HEARTBEAT_TTL_SECONDS)


async def _get_last_heartbeat(agent_id: str) -> float | None:
    """Get the last heartbeat timestamp for an agent.

    Returns:
        Unix timestamp of last heartbeat, or None if no record.
    """
    key = f"{HEARTBEAT_KEY_PREFIX}:{agent_id}"
    val = await redis_cache.get(key)
    if val is None:
        return None
    return float(val)


# ─── Heartbeat consumer ─────────────────────────────────────────────────────


async def _consume_heartbeats() -> None:
    """Consume heartbeats from Kafka and record in Redis."""
    consumer = await create_consumer(
        Topics.AGENT_HEARTBEAT,
        group_id="nexus-health-monitor",
    )
    logger.info("health_monitor_heartbeat_consumer_started")

    try:
        async for msg in consumer:
            try:
                data = msg.value
                agent_id = data.get("agent_id")
                if agent_id:
                    await _record_heartbeat(agent_id)
            except Exception as exc:
                logger.warning(
                    "heartbeat_parse_error",
                    error=str(exc),
                )
    finally:
        await consumer.stop()


# ─── Auto-fail scanner ──────────────────────────────────────────────────────


async def _scan_and_fail_silent(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Scan for tasks assigned to agents that have gone silent.

    Runs every SCAN_INTERVAL_SECONDS. If an agent's last heartbeat
    is older than SILENCE_THRESHOLD_SECONDS, all its running tasks
    are auto-failed.
    """
    while True:
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)

        try:
            async with db_session_factory() as session:
                # Find all running tasks with assigned agents
                stmt = select(Task).where(
                    Task.status == TaskStatus.RUNNING.value,
                    Task.assigned_agent_id.isnot(None),
                )
                result = await session.execute(stmt)
                running_tasks = result.scalars().all()

                if not running_tasks:
                    continue

                now = time.time()
                failed_count = 0

                for task in running_tasks:
                    agent_id = task.assigned_agent_id
                    if agent_id is None:
                        continue

                    last_hb = await _get_last_heartbeat(agent_id)

                    # No heartbeat recorded or too old
                    if last_hb is None or (now - last_hb) > SILENCE_THRESHOLD_SECONDS:
                        silence_duration = int(now - last_hb) if last_hb else "never"

                        logger.warning(
                            "auto_failing_silent_task",
                            task_id=str(task.id),
                            agent_id=agent_id,
                            silence_seconds=silence_duration,
                        )

                        # Update task status in DB
                        await session.execute(
                            update(Task)
                            .where(Task.id == task.id)
                            .values(
                                status=TaskStatus.FAILED.value,
                                error=(
                                    f"Agent {agent_id} heartbeat silence "
                                    f"({silence_duration}s). Auto-failed."
                                ),
                                completed_at=datetime.now(UTC),
                            )
                        )

                        # Write audit log
                        audit = AuditLog(
                            task_id=str(task.id),
                            trace_id=task.trace_id,
                            agent_id=agent_id,
                            event_type="auto_fail_heartbeat_silence",
                            event_data={
                                "silence_seconds": silence_duration,
                                "threshold_seconds": SILENCE_THRESHOLD_SECONDS,
                            },
                        )
                        session.add(audit)

                        # Publish error response to agent.responses
                        error_response = AgentResponse(
                            task_id=task.id,
                            trace_id=task.trace_id,
                            agent_id=agent_id,
                            payload={},
                            status="failed",
                            error=(
                                f"Agent heartbeat silence ({silence_duration}s). "
                                "Task auto-failed by health monitor."
                            ),
                        )
                        await publish(
                            Topics.AGENT_RESPONSES,
                            error_response,
                            key=str(task.id),
                        )

                        failed_count += 1

                if failed_count > 0:
                    await session.commit()
                    logger.info(
                        "auto_fail_scan_complete",
                        failed_count=failed_count,
                    )

        except Exception as exc:
            logger.error(
                "health_monitor_scan_error",
                error=str(exc),
            )


# ─── Public entry point ─────────────────────────────────────────────────────


async def run_health_monitor(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Run the health monitor: heartbeat consumer + auto-fail scanner.

    Args:
        db_session_factory: Async session factory for DB operations.
    """
    logger.info("health_monitor_starting")

    # Run both coroutines concurrently
    await asyncio.gather(
        _consume_heartbeats(),
        _scan_and_fail_silent(db_session_factory),
    )
