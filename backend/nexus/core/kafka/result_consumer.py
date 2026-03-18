"""Task result consumer — bridges agent.responses to task DB updates.

Consumes AgentResponse messages from agent.responses topic, updates task
status in PostgreSQL, publishes final results to task.results, and
broadcasts events via Redis pub/sub for WebSocket streaming.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.kafka.consumer import check_idempotency, create_consumer
from nexus.core.kafka.dead_letter import MAX_RETRIES, increment_retry, publish_dead_letter
from nexus.core.kafka.producer import publish
from nexus.core.kafka.schemas import AgentResponse, TaskResult
from nexus.core.kafka.topics import Topics
from nexus.core.redis.clients import redis_pubsub
from nexus.db.models import Task, TaskStatus

logger = structlog.get_logger()


async def run_result_consumer(db_session_factory: Callable[..., Any]) -> None:
    """Consume agent.responses and update task state to completion.

    This consumer closes the task lifecycle loop by:
    1. Receiving AgentResponse messages from all agents
    2. Updating task status, output, and completion time in PostgreSQL
    3. Publishing TaskResult to task.results topic
    4. Broadcasting events via Redis pub/sub for WebSocket dashboard

    Runs indefinitely until stopped. Idempotent — duplicate messages are skipped.
    """
    consumer = await create_consumer(Topics.AGENT_RESPONSES, group_id="result-consumer")
    logger.info("result_consumer_started")

    try:
        async for msg in consumer:
            try:
                await _handle_response(msg.value, db_session_factory)
            except Exception as exc:
                raw = msg.value if isinstance(msg.value, dict) else {}
                message_id = raw.get("message_id", "unknown")
                task_id = raw.get("task_id")
                retry_count = await increment_retry(str(message_id))

                if retry_count >= MAX_RETRIES:
                    logger.error(
                        "result_consumer_max_retries",
                        message_id=message_id,
                        task_id=task_id,
                        retry_count=retry_count,
                        error=str(exc),
                    )
                    await publish_dead_letter(
                        source_topic=Topics.AGENT_RESPONSES,
                        raw_message=raw,
                        error=str(exc),
                        task_id=str(task_id) if task_id else None,
                        db_session_factory=db_session_factory,
                    )
                else:
                    logger.warning(
                        "result_consumer_retry",
                        message_id=message_id,
                        task_id=task_id,
                        retry_count=retry_count,
                        error=str(exc),
                    )
    finally:
        await consumer.stop()
        logger.info("result_consumer_stopped")


async def _handle_response(
    raw: dict[str, Any],
    db_session_factory: Callable[..., Any],
) -> None:
    """Process a single AgentResponse message."""
    try:
        response = AgentResponse.model_validate(raw)
    except Exception:
        logger.warning(
            "result_consumer_invalid_message",
            raw_keys=list(raw.keys()),
        )
        return

    msg_id = str(response.message_id)
    task_id = str(response.task_id)

    # Idempotency: skip already-processed responses
    is_new = await check_idempotency(f"result:{msg_id}")
    if not is_new:
        logger.info(
            "result_consumer_duplicate_skipped",
            message_id=msg_id,
            task_id=task_id,
        )
        return

    # Skip CEO orchestration responses (decomposition, subtask tracking)
    if response.output and response.output.get("action") in (
        "delegated_to_engineer",
        "decomposed",
        "subtask_tracked",
        "aggregated_and_sent_to_qa",
    ):
        logger.debug(
            "result_consumer_skip_ceo_action", task_id=task_id, action=response.output.get("action")
        )
        return

    # Check if this response is for a subtask (has parent_task_id)
    async with db_session_factory() as session:
        is_subtask = await _check_is_subtask(session, task_id)

    if is_subtask:
        # Forward subtask completion to CEO for aggregation
        await _forward_to_ceo(response, db_session_factory)
        return

    # Direct task result — update DB and publish
    task_status = _map_status(response.status)

    async with db_session_factory() as session:
        await _update_task_in_db(session, task_id, task_status, response)
        await session.commit()

    task_result = TaskResult(
        task_id=response.task_id,
        trace_id=response.trace_id,
        agent_id=response.agent_id,
        payload={},
        status=task_status,
        output=response.output,
        error=response.error,
    )
    await publish(Topics.TASK_RESULTS, task_result, key=task_id)

    event = {
        "event": "task_result",
        "task_id": task_id,
        "status": task_status,
        "output": response.output,
        "error": response.error,
        "tokens_used": response.tokens_used,
    }
    await redis_pubsub.publish(f"agent_activity:{task_id}", json.dumps(event))

    logger.info(
        "task_result_processed",
        task_id=task_id,
        status=task_status,
        agent_id=response.agent_id,
        tokens_used=response.tokens_used,
    )


async def _check_is_subtask(session: AsyncSession, task_id: str) -> bool:
    """Check if a task has a parent_task_id (is a subtask)."""
    stmt = select(Task.parent_task_id).where(Task.id == task_id)
    result = await session.execute(stmt)
    parent_id = result.scalar_one_or_none()
    return parent_id is not None


async def _forward_to_ceo(
    response: AgentResponse,
    db_session_factory: Callable[..., Any],
) -> None:
    """Forward a subtask response to the CEO for aggregation."""
    task_id = str(response.task_id)

    # Look up the parent task ID
    async with db_session_factory() as session:
        stmt = select(Task).where(Task.id == task_id)
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()

        if task is None:
            logger.warning("forward_to_ceo_task_not_found", task_id=task_id)
            return

        parent_task_id = str(task.parent_task_id)

        # Update subtask status in DB
        task_status = _map_status(response.status)
        task.status = task_status
        task.output = response.output
        task.error = response.error
        task.tokens_used = response.tokens_used
        from datetime import datetime

        task.completed_at = datetime.now(UTC)
        await session.commit()

    # Extract the result text from the response output
    subtask_output = ""
    if response.output:
        subtask_output = response.output.get("result", str(response.output))

    # Publish to task.queue so CEO picks it up as a response notification
    from nexus.core.kafka.schemas import AgentCommand

    ceo_command = AgentCommand(
        task_id=response.task_id,
        trace_id=response.trace_id,
        agent_id=response.agent_id,
        payload={
            "_response_aggregation": True,
            "subtask_id": task_id,
            "parent_task_id": parent_task_id,
            "subtask_output": subtask_output,
            "subtask_status": response.status,
        },
        target_role="ceo",
        instruction="Subtask completed — aggregate responses",
    )
    await publish(Topics.TASK_QUEUE, ceo_command, key=str(parent_task_id))

    # Broadcast subtask completion for dashboard
    event = {
        "event": "subtask_completed",
        "task_id": task_id,
        "parent_task_id": parent_task_id,
        "status": response.status,
        "tokens_used": response.tokens_used,
    }
    await redis_pubsub.publish(f"agent_activity:{parent_task_id}", json.dumps(event))

    logger.info(
        "subtask_forwarded_to_ceo",
        subtask_id=task_id,
        parent_task_id=parent_task_id,
        status=response.status,
    )


def _map_status(agent_status: str) -> str:
    """Map AgentResponse status to TaskStatus value."""
    mapping = {
        "success": TaskStatus.COMPLETED.value,
        "failed": TaskStatus.FAILED.value,
        "partial": TaskStatus.FAILED.value,
        "escalated": TaskStatus.ESCALATED.value,
    }
    return mapping.get(agent_status, TaskStatus.COMPLETED.value)


async def _update_task_in_db(
    session: AsyncSession,
    task_id: str,
    status: str,
    response: AgentResponse,
) -> None:
    """Update task record with completion data."""
    stmt = select(Task).where(Task.id == task_id)
    result = await session.execute(stmt)
    task = result.scalar_one_or_none()

    if task is None:
        logger.warning("result_consumer_task_not_found", task_id=task_id)
        return

    task.status = status
    task.output = response.output
    task.error = response.error
    task.tokens_used = response.tokens_used
    task.completed_at = datetime.now(UTC)
    session.add(task)

    logger.info(
        "task_db_updated",
        task_id=task_id,
        status=status,
        tokens_used=response.tokens_used,
    )
