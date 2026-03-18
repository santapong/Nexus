"""Temporal workflow definitions for long-running tasks.

Workflows define the orchestration logic. They are deterministic
and must not perform I/O directly — all I/O happens in activities.
"""

from __future__ import annotations

import structlog

from nexus.workflows.schemas import TaskWorkflowInput, TaskWorkflowOutput

logger = structlog.get_logger()


async def task_execution_workflow(
    input_data: TaskWorkflowInput,
) -> TaskWorkflowOutput:
    """Main task execution workflow.

    Orchestrates the full task lifecycle for long-running tasks.
    Temporal ensures this workflow survives worker crashes and restarts.

    The workflow delegates actual execution to the existing Kafka-based
    agent pipeline via the execute_task_activity.

    Args:
        input_data: Task details.

    Returns:
        TaskWorkflowOutput with final results.
    """
    logger.info(
        "temporal_workflow_started",
        task_id=input_data.task_id,
        trace_id=input_data.trace_id,
        estimated_minutes=input_data.estimated_duration_minutes,
    )

    from nexus.workflows.activities import execute_task_activity

    result = await execute_task_activity(input_data)

    logger.info(
        "temporal_workflow_completed",
        task_id=input_data.task_id,
        status=result.status,
        duration_seconds=result.duration_seconds,
    )

    return result
