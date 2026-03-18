"""Temporal activities — the actual work units executed by workers.

Activities wrap existing agent logic so the same code works
with both Taskiq (short tasks) and Temporal (long-running tasks).
"""

from __future__ import annotations

import asyncio
import time

import structlog

from nexus.integrations.temporal.schemas import (
    SubtaskActivityInput,
    SubtaskActivityOutput,
    TaskWorkflowInput,
    TaskWorkflowOutput,
)

logger = structlog.get_logger()


async def execute_task_activity(input_data: TaskWorkflowInput) -> TaskWorkflowOutput:
    """Execute a task through the standard agent pipeline.

    This activity wraps the existing Kafka-based task flow,
    making it durable via Temporal. If the worker crashes mid-execution,
    Temporal will retry this activity on another worker.

    Args:
        input_data: Task details including instruction and workspace.

    Returns:
        TaskWorkflowOutput with execution results.
    """
    start_time = time.monotonic()

    logger.info(
        "temporal_activity_started",
        task_id=input_data.task_id,
        trace_id=input_data.trace_id,
    )

    try:
        from nexus.integrations.kafka.producer import publish
        from nexus.integrations.kafka.schemas import AgentCommand
        from nexus.integrations.kafka.topics import Topics

        command = AgentCommand(
            task_id=input_data.task_id,
            trace_id=input_data.trace_id,
            agent_id="temporal-worker",
            payload={
                "source": "temporal",
                "workspace_id": input_data.workspace_id,
            },
            target_role="ceo",
            instruction=input_data.instruction,
        )
        await publish(Topics.TASK_QUEUE, command, key=input_data.task_id)

        # Poll DB for task completion
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from nexus.db.models import Task
        from nexus.settings import settings

        engine = create_async_engine(settings.database_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        max_wait = input_data.estimated_duration_minutes * 60 or 3600
        poll_interval = 10
        elapsed = 0

        while elapsed < max_wait:
            async with session_factory() as session:
                stmt = select(Task).where(Task.id == input_data.task_id)
                result = await session.execute(stmt)
                task = result.scalar_one_or_none()

                if task and task.status in ("completed", "failed"):
                    duration = int(time.monotonic() - start_time)
                    await engine.dispose()
                    return TaskWorkflowOutput(
                        task_id=input_data.task_id,
                        status=task.status,
                        output=task.output,
                        error=task.error,
                        tokens_used=task.tokens_used or 0,
                        duration_seconds=duration,
                    )

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        await engine.dispose()
        duration = int(time.monotonic() - start_time)
        return TaskWorkflowOutput(
            task_id=input_data.task_id,
            status="failed",
            error=f"Task timed out after {max_wait}s",
            duration_seconds=duration,
        )

    except Exception as exc:
        logger.error(
            "temporal_activity_failed",
            task_id=input_data.task_id,
            error=str(exc),
        )
        duration = int(time.monotonic() - start_time)
        return TaskWorkflowOutput(
            task_id=input_data.task_id,
            status="failed",
            error=str(exc),
            duration_seconds=duration,
        )


async def execute_subtask_activity(
    input_data: SubtaskActivityInput,
) -> SubtaskActivityOutput:
    """Execute a single subtask for a specific agent role.

    Args:
        input_data: Subtask details including agent role and instruction.

    Returns:
        SubtaskActivityOutput with execution results.
    """
    logger.info(
        "temporal_subtask_started",
        task_id=input_data.task_id,
        agent_role=input_data.agent_role,
    )

    try:
        from nexus.integrations.kafka.producer import publish
        from nexus.integrations.kafka.schemas import AgentCommand
        from nexus.integrations.kafka.topics import Topics

        command = AgentCommand(
            task_id=input_data.task_id,
            trace_id=input_data.trace_id,
            agent_id="temporal-worker",
            payload={"source": "temporal"},
            target_role=input_data.agent_role,
            instruction=input_data.instruction,
        )
        await publish(Topics.AGENT_COMMANDS, command, key=input_data.task_id)

        return SubtaskActivityOutput(
            task_id=input_data.task_id,
            agent_role=input_data.agent_role,
            status="dispatched",
            output="Subtask dispatched to agent via Kafka",
        )

    except Exception as exc:
        logger.error(
            "temporal_subtask_failed",
            task_id=input_data.task_id,
            error=str(exc),
        )
        return SubtaskActivityOutput(
            task_id=input_data.task_id,
            agent_role=input_data.agent_role,
            status="failed",
            error=str(exc),
        )
