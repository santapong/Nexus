from __future__ import annotations

from typing import Any

import structlog
from litestar import Controller, get, post
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import ApprovalStatus, HumanApproval
from nexus.tools.guards import resolve_approval

logger = structlog.get_logger()


class ApprovalResponse(BaseModel):
    id: str
    task_id: str
    agent_id: str
    tool_name: str
    action_description: str
    status: str
    requested_at: str
    resolved_at: str | None = None
    resolved_by: str | None = None


class ResolveApprovalRequest(BaseModel):
    approved: bool
    resolved_by: str = "human"


class ApprovalController(Controller):
    path = "/approvals"

    @get()
    async def list_pending_approvals(
        self,
        db_session: AsyncSession,
    ) -> list[ApprovalResponse]:
        """List all pending approval requests."""
        stmt = (
            select(HumanApproval)
            .where(HumanApproval.status == ApprovalStatus.PENDING.value)
            .order_by(HumanApproval.requested_at.desc())
        )
        result = await db_session.execute(stmt)
        approvals = result.scalars().all()

        return [
            ApprovalResponse(
                id=str(a.id),
                task_id=str(a.task_id),
                agent_id=str(a.agent_id),
                tool_name=a.tool_name,
                action_description=a.action_description,
                status=a.status,
                requested_at=str(a.requested_at),
                resolved_at=str(a.resolved_at) if a.resolved_at else None,
                resolved_by=a.resolved_by,
            )
            for a in approvals
        ]

    @post("/{approval_id:str}/resolve")
    async def resolve(
        self,
        approval_id: str,
        data: ResolveApprovalRequest,
        db_session: AsyncSession,
    ) -> dict[str, Any]:
        """Approve or reject a pending approval request."""
        record = await resolve_approval(
            session=db_session,
            approval_id=approval_id,
            approved=data.approved,
            resolved_by=data.resolved_by,
        )

        if record is None:
            return {"error": "Approval not found"}

        logger.info(
            "approval_resolved",
            approval_id=approval_id,
            approved=data.approved,
            resolved_by=data.resolved_by,
        )

        return {
            "id": str(record.id),
            "status": record.status,
            "resolved_by": record.resolved_by,
        }
