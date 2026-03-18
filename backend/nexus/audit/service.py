"""Audit logging service.

Provides a centralized function and event type enum for writing
structured audit events to the audit_log table. All agent actions,
prompt changes, budget events, and approval flows should go through
this service.
"""

from __future__ import annotations

import enum
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import AuditLog

logger = structlog.get_logger()


class AuditEventType(enum.StrEnum):
    """Standardized event types for the audit log."""

    TASK_RECEIVED = "task_received"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    TOOL_CALL_LIMIT_REACHED = "tool_call_limit_reached"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    BUDGET_EXCEEDED = "budget_exceeded"
    PROMPT_ACTIVATED = "prompt_activated"
    PROMPT_ROLLBACK = "prompt_rollback"
    PROMPT_CREATED = "prompt_created"
    HEARTBEAT_SILENCE = "auto_fail_heartbeat_silence"


async def log_event(
    *,
    session: AsyncSession,
    task_id: str,
    trace_id: str,
    agent_id: str,
    event_type: AuditEventType | str,
    event_data: dict[str, Any],
) -> None:
    """Write an audit event to the audit_log table.

    Args:
        session: Active database session (caller manages commit).
        task_id: Task UUID string.
        trace_id: Trace UUID string for request correlation.
        agent_id: Agent identifier (UUID string or role-based ID).
        event_type: Standardized event type from AuditEventType.
        event_data: Structured event payload (stored as JSONB).
    """
    event_type_str = event_type.value if isinstance(event_type, AuditEventType) else event_type

    entry = AuditLog(
        task_id=task_id,
        trace_id=trace_id,
        agent_id=agent_id,
        event_type=event_type_str,
        event_data=event_data,
    )
    session.add(entry)

    logger.info(
        "audit_event",
        event_type=event_type_str,
        task_id=task_id,
        agent_id=agent_id,
    )
