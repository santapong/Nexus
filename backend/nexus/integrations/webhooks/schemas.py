"""Webhook event payload schemas.

Defines the standard envelope for all webhook deliveries and
the specific payloads for each event type.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class WebhookEventType(StrEnum):
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_PAUSED = "task.paused"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_RESOLVED = "approval.resolved"
    AGENT_ERROR = "agent.error"


class WebhookPayload(BaseModel):
    """Standard webhook delivery envelope."""

    event_id: str
    event_type: WebhookEventType
    workspace_id: str
    timestamp: str
    data: dict[str, Any]


class TaskEventData(BaseModel):
    """Payload for task lifecycle events."""

    task_id: str
    trace_id: str
    status: str
    instruction_preview: str  # first 200 chars
    assigned_agent: str | None = None
    output_preview: str | None = None
    error: str | None = None
    tokens_used: int = 0


class ApprovalEventData(BaseModel):
    """Payload for approval lifecycle events."""

    approval_id: str
    task_id: str
    agent_id: str
    tool_name: str
    action_description: str
    status: str
    resolved_by: str | None = None
