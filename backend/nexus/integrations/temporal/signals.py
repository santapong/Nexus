"""Temporal signal definitions for human-in-the-loop workflows.

Signals allow external events to influence running workflows:
- Human approval/rejection of pending actions
- Task progress updates from activities
- Task cancellation requests

When Temporal is properly configured, these become real Temporal signals.
In the current implementation, they work via Redis pub/sub as a bridge.
"""

from __future__ import annotations

import json

import structlog

from nexus.core.redis.clients import redis_pubsub
from nexus.integrations.temporal.schemas import HumanApprovalSignal, TaskProgressSignal

logger = structlog.get_logger()

# Signal channel patterns
_APPROVAL_CHANNEL = "temporal:approval:{task_id}"
_PROGRESS_CHANNEL = "temporal:progress:{task_id}"


async def send_approval_signal(
    task_id: str,
    approved: bool,
    resolved_by: str = "",
    comment: str = "",
) -> None:
    """Send a human approval/rejection signal to a waiting workflow.

    Args:
        task_id: The task waiting for approval.
        approved: Whether the action is approved.
        resolved_by: Who approved/rejected.
        comment: Optional comment.
    """
    signal = HumanApprovalSignal(
        approved=approved,
        resolved_by=resolved_by,
        comment=comment,
    )

    channel = _APPROVAL_CHANNEL.format(task_id=task_id)
    await redis_pubsub.publish(channel, signal.model_dump_json())

    logger.info(
        "approval_signal_sent",
        task_id=task_id,
        approved=approved,
        resolved_by=resolved_by,
    )


async def send_progress_signal(
    task_id: str,
    step: str,
    progress_pct: int = 0,
    message: str = "",
) -> None:
    """Send a progress update signal to a running workflow.

    Args:
        task_id: The task being executed.
        step: Current execution step name.
        progress_pct: Completion percentage (0-100).
        message: Optional progress message.
    """
    signal = TaskProgressSignal(
        step=step,
        progress_pct=progress_pct,
        message=message,
    )

    channel = _PROGRESS_CHANNEL.format(task_id=task_id)
    await redis_pubsub.publish(channel, signal.model_dump_json())


async def wait_for_approval(
    task_id: str,
    timeout_seconds: int = 3600,
) -> HumanApprovalSignal | None:
    """Wait for a human approval signal via Redis pub/sub.

    Args:
        task_id: The task waiting for approval.
        timeout_seconds: Max wait time (default: 1 hour).

    Returns:
        HumanApprovalSignal if received, None if timed out.
    """
    import asyncio

    channel = _APPROVAL_CHANNEL.format(task_id=task_id)
    pubsub = redis_pubsub.pubsub()

    try:
        await pubsub.subscribe(channel)

        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=5.0,
            )
            if message and message["type"] == "message":
                data = json.loads(message["data"])
                return HumanApprovalSignal.model_validate(data)

        return None
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
