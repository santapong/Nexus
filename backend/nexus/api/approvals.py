from __future__ import annotations

from typing import Any

import structlog
from litestar import Controller, Request, get, post
from litestar.exceptions import NotAuthorizedException, NotFoundException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.auth import require_auth_user
from nexus.db.models import ApprovalStatus, HumanApproval, Task
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


class ApprovalController(Controller):
    path = "/approvals"

    @get()
    async def list_pending_approvals(
        self,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
    ) -> list[ApprovalResponse]:
        """List pending approval requests for the current workspace.

        Requires authentication — listing approvals across all workspaces
        would leak which agents are pending what tool calls in other tenants.
        """
        auth_user = require_auth_user(request)
        if not auth_user.workspace_id:
            raise NotAuthorizedException(detail="No workspace associated with this user")

        stmt = (
            select(HumanApproval)
            .join(Task, HumanApproval.task_id == Task.id)
            .where(
                HumanApproval.status == ApprovalStatus.PENDING.value,
                Task.workspace_id == auth_user.workspace_id,
            )
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
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
    ) -> dict[str, Any]:
        """Approve or reject a pending approval request.

        The resolved_by field is set from the authenticated JWT user,
        not from the request body. The approval must belong to a task
        in the caller's workspace.
        """
        auth_user = require_auth_user(request)
        if not auth_user.workspace_id:
            raise NotAuthorizedException(detail="No workspace associated with this user")

        # Confirm the approval belongs to the caller's workspace before
        # resolving — otherwise a token holder could approve any tenant's
        # irreversible actions just by guessing approval IDs.
        ownership_stmt = (
            select(HumanApproval.id)
            .join(Task, HumanApproval.task_id == Task.id)
            .where(
                HumanApproval.id == approval_id,
                Task.workspace_id == auth_user.workspace_id,
            )
        )
        ownership_result = await db_session.execute(ownership_stmt)
        if ownership_result.scalar_one_or_none() is None:
            raise NotFoundException(detail="Approval not found")

        resolved_by = auth_user.email or auth_user.user_id

        record = await resolve_approval(
            session=db_session,
            approval_id=approval_id,
            approved=data.approved,
            resolved_by=resolved_by,
        )

        if record is None:
            raise NotFoundException(detail="Approval not found")

        logger.info(
            "approval_resolved",
            approval_id=approval_id,
            approved=data.approved,
            resolved_by=resolved_by,
            workspace_id=auth_user.workspace_id,
        )

        return {
            "id": str(record.id),
            "status": record.status,
            "resolved_by": record.resolved_by,
        }
