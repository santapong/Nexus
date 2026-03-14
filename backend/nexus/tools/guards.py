from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.audit.service import AuditEventType, log_event
from nexus.db.models import ApprovalStatus, HumanApproval

logger = structlog.get_logger()

# Polling interval for approval check
_APPROVAL_POLL_SECONDS = 2.0
# Maximum time to wait for approval before timing out
_APPROVAL_TIMEOUT_SECONDS = 3600.0  # 1 hour


class IrreversibleAction(BaseModel):
    """Describes an action that requires human approval before execution."""

    action: str
    description: str
    task_id: str


class ApprovalDeniedError(Exception):
    """Raised when a human rejects an irreversible action."""


class ApprovalTimeoutError(Exception):
    """Raised when approval is not received within the timeout period."""


async def require_approval(
    *,
    session: AsyncSession,
    agent_id: str,
    action: IrreversibleAction,
    kafka_publish: object | None = None,
) -> None:
    """Block execution until a human approves the irreversible action.

    Creates a HumanApproval record, publishes to human.input_needed,
    and polls until the approval is resolved.

    Args:
        session: Database session for creating/reading approval records.
        agent_id: The agent requesting approval.
        action: Description of the irreversible action.
        kafka_publish: Optional callable to publish to human.input_needed topic.

    Raises:
        ApprovalDeniedError: If the human rejects the action.
        ApprovalTimeoutError: If no response within timeout.
    """
    # Create approval record
    approval = HumanApproval(
        task_id=action.task_id,
        agent_id=agent_id,
        tool_name=action.action,
        action_description=action.description,
        status=ApprovalStatus.PENDING.value,
    )
    session.add(approval)
    await session.flush()
    approval_id = approval.id

    # Audit: approval_requested
    await log_event(
        session=session,
        task_id=action.task_id,
        trace_id=action.task_id,
        agent_id=agent_id,
        event_type=AuditEventType.APPROVAL_REQUESTED,
        event_data={
            "approval_id": str(approval_id),
            "tool_name": action.action,
            "description": action.description,
        },
    )

    logger.info(
        "approval_requested",
        approval_id=str(approval_id),
        task_id=action.task_id,
        agent_id=agent_id,
        action=action.action,
        description=action.description,
    )

    # Poll for resolution
    elapsed = 0.0
    while elapsed < _APPROVAL_TIMEOUT_SECONDS:
        await asyncio.sleep(_APPROVAL_POLL_SECONDS)
        elapsed += _APPROVAL_POLL_SECONDS

        stmt = select(HumanApproval).where(HumanApproval.id == approval_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()

        if record is None:
            msg = f"Approval record {approval_id} disappeared"
            raise RuntimeError(msg)

        if record.status == ApprovalStatus.APPROVED.value:
            logger.info(
                "approval_granted",
                approval_id=str(approval_id),
                task_id=action.task_id,
                resolved_by=record.resolved_by,
            )
            return

        if record.status == ApprovalStatus.REJECTED.value:
            logger.warning(
                "approval_denied",
                approval_id=str(approval_id),
                task_id=action.task_id,
                resolved_by=record.resolved_by,
            )
            raise ApprovalDeniedError(
                f"Action '{action.action}' rejected by {record.resolved_by}: "
                f"{action.description}"
            )

    raise ApprovalTimeoutError(
        f"Approval for '{action.action}' timed out after {_APPROVAL_TIMEOUT_SECONDS}s"
    )


async def resolve_approval(
    *,
    session: AsyncSession,
    approval_id: str,
    approved: bool,
    resolved_by: str,
) -> HumanApproval | None:
    """Resolve a pending approval request.

    Args:
        session: Database session.
        approval_id: The approval record ID.
        approved: True to approve, False to reject.
        resolved_by: Identifier of the human who resolved it.

    Returns:
        The updated approval record, or None if not found.
    """
    stmt = select(HumanApproval).where(HumanApproval.id == approval_id)
    result = await session.execute(stmt)
    record = result.scalar_one_or_none()

    if record is None:
        return None

    record.status = (
        ApprovalStatus.APPROVED.value if approved else ApprovalStatus.REJECTED.value
    )
    record.resolved_at = datetime.now(timezone.utc)
    record.resolved_by = resolved_by
    await session.flush()

    # Audit: approval_resolved
    await log_event(
        session=session,
        task_id=str(record.task_id),
        trace_id=str(record.task_id),
        agent_id=str(record.agent_id),
        event_type=AuditEventType.APPROVAL_RESOLVED,
        event_data={
            "approval_id": approval_id,
            "approved": approved,
            "resolved_by": resolved_by,
            "tool_name": record.tool_name,
        },
    )

    return record
