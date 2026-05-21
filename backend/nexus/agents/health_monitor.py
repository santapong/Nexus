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

from nexus.core.kafka.consumer import create_consumer
from nexus.core.kafka.producer import publish
from nexus.core.kafka.schemas import AgentResponse
from nexus.core.kafka.topics import Topics
from nexus.core.redis.clients import redis_cache
from nexus.db.models import AuditLog, Task, TaskStatus

logger = structlog.get_logger()

# ─── Constants ───────────────────────────────────────────────────────────────

HEARTBEAT_KEY_PREFIX = "heartbeat"
HEARTBEAT_TTL_SECONDS = 600  # 10 min TTL (cleanup buffer)
SILENCE_THRESHOLD_SECONDS = 300  # 5 minutes = considered dead
SCAN_INTERVAL_SECONDS = 60  # Check every 60 seconds

# Per-agent Redis hash holding the health-monitor's view of agent status.
# Used by the Lua script below to atomically claim a "failed" transition,
# so concurrent scanners and a heartbeating agent cannot race.
AGENT_STATUS_KEY_PREFIX = "agent_status"
AGENT_STATUS_TTL_SECONDS = 3600  # 1 hour

# Atomic Redis-Lua script: read the last heartbeat timestamp (KEYS[1]) and,
# only if it is older than the threshold (ARGV[1]) AND the status hash
# (KEYS[2]) is not already marked "failed", set the status to "failed"
# atomically. Returns 1 if we just claimed the failure, 0 otherwise. This
# eliminates the read-then-compare race where a healthy agent heartbeating
# concurrently with the scanner could be falsely auto-failed.
SILENCE_CHECK_LUA = """
local hb = redis.call('GET', KEYS[1])
if hb == false then
    if redis.call('HGET', KEYS[2], 'status') == 'failed' then
        return 0
    end
    redis.call('HSET', KEYS[2], 'status', 'failed')
    redis.call('EXPIRE', KEYS[2], tonumber(ARGV[2]))
    return 1
end
if tonumber(hb) < tonumber(ARGV[1]) then
    if redis.call('HGET', KEYS[2], 'status') == 'failed' then
        return 0
    end
    redis.call('HSET', KEYS[2], 'status', 'failed')
    redis.call('EXPIRE', KEYS[2], tonumber(ARGV[2]))
    return 1
end
return 0
"""


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

                    # Atomic check-and-claim via Lua: returns 1 only if the
                    # agent is genuinely silent AND no prior scanner already
                    # claimed the failure. Eliminates the fetch-then-compare
                    # race that could falsely auto-fail a healthy agent
                    # heartbeating concurrently with the scanner.
                    hb_key = f"{HEARTBEAT_KEY_PREFIX}:{agent_id}"
                    status_key = f"{AGENT_STATUS_KEY_PREFIX}:{agent_id}"
                    threshold_ts = now - SILENCE_THRESHOLD_SECONDS
                    claimed = await redis_cache.eval(
                        SILENCE_CHECK_LUA,
                        2,
                        hb_key,
                        status_key,
                        str(threshold_ts),
                        str(AGENT_STATUS_TTL_SECONDS),
                    )

                    if int(claimed) == 1:
                        last_hb = await _get_last_heartbeat(agent_id)
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
