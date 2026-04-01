"""Workspace invitation API — team collaboration.

Allows workspace owners/admins to invite users via email.
Invitations expire after 7 days and can be accepted or declined.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from litestar import Controller, delete, get, post
from sqlalchemy import select

from nexus.db.models import User, Workspace, WorkspaceMember
from nexus.db.session import sqlalchemy_config

logger = structlog.get_logger()

# Invitation tokens are stored in workspace_members with status 'invited'
_INVITE_TOKEN_LENGTH = 32
_INVITE_EXPIRY_DAYS = 7


class InvitationController(Controller):
    path = "/api/workspaces/{workspace_id:uuid}/invitations"

    @post("/")
    async def invite_member(
        self,
        workspace_id: UUID,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Invite a user to a workspace by email.

        Args:
            workspace_id: Target workspace.
            data: Must contain 'email' and optionally 'role' (default: 'member').

        Returns:
            Invitation details including the invite token.
        """
        email = data.get("email", "").strip().lower()
        role = data.get("role", "member")

        if not email:
            return {"error": "Email is required"}

        if role not in ("admin", "member", "viewer"):
            return {"error": "Role must be one of: admin, member, viewer"}

        async with sqlalchemy_config.get_session() as session:
            # Verify workspace exists
            ws = await session.get(Workspace, workspace_id)
            if not ws:
                return {"error": "Workspace not found"}

            # Check if user already exists
            user_result = await session.execute(
                select(User).where(User.email == email)
            )
            existing_user = user_result.scalar_one_or_none()

            # Check if already a member
            if existing_user:
                member_result = await session.execute(
                    select(WorkspaceMember).where(
                        WorkspaceMember.workspace_id == workspace_id,
                        WorkspaceMember.user_id == existing_user.id,
                    )
                )
                if member_result.scalar_one_or_none():
                    return {"error": "User is already a member of this workspace"}

            # Generate invite token
            invite_token = secrets.token_urlsafe(_INVITE_TOKEN_LENGTH)

            # Create pending membership
            member = WorkspaceMember(
                workspace_id=workspace_id,
                user_id=existing_user.id if existing_user else None,
                role=role,
                invite_token=invite_token,
                invite_email=email,
                invited_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=_INVITE_EXPIRY_DAYS),
            )
            session.add(member)
            await session.commit()

            logger.info(
                "invitation_created",
                workspace_id=str(workspace_id),
                email=email,
                role=role,
            )

            return {
                "workspace_id": str(workspace_id),
                "email": email,
                "role": role,
                "invite_token": invite_token,
                "expires_at": member.expires_at.isoformat() if member.expires_at else None,
            }

    @get("/")
    async def list_invitations(
        self,
        workspace_id: UUID,
    ) -> dict[str, Any]:
        """List all pending invitations for a workspace.

        Args:
            workspace_id: Target workspace.

        Returns:
            List of pending invitations.
        """
        async with sqlalchemy_config.get_session() as session:
            result = await session.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.invite_token.isnot(None),
                )
            )
            invitations = result.scalars().all()

            return {
                "workspace_id": str(workspace_id),
                "invitations": [
                    {
                        "id": str(inv.id),
                        "email": inv.invite_email,
                        "role": inv.role,
                        "invited_at": inv.invited_at.isoformat() if inv.invited_at else None,
                        "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
                    }
                    for inv in invitations
                ],
            }


class InvitationAcceptController(Controller):
    path = "/api/invitations"

    @post("/accept")
    async def accept_invitation(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Accept a workspace invitation using the invite token.

        Args:
            data: Must contain 'invite_token' and 'user_id'.

        Returns:
            Membership details.
        """
        invite_token = data.get("invite_token", "")
        user_id = data.get("user_id", "")

        if not invite_token or not user_id:
            return {"error": "invite_token and user_id are required"}

        async with sqlalchemy_config.get_session() as session:
            # Find invitation
            result = await session.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.invite_token == invite_token,
                )
            )
            invitation = result.scalar_one_or_none()

            if not invitation:
                return {"error": "Invalid invitation token"}

            # Check expiry
            if invitation.expires_at and invitation.expires_at < datetime.now(UTC):
                return {"error": "Invitation has expired"}

            # Accept: set user_id and clear invite token
            invitation.user_id = UUID(user_id)
            invitation.invite_token = None
            invitation.invite_email = None
            await session.commit()

            logger.info(
                "invitation_accepted",
                workspace_id=str(invitation.workspace_id),
                user_id=user_id,
                role=invitation.role,
            )

            return {
                "workspace_id": str(invitation.workspace_id),
                "user_id": user_id,
                "role": invitation.role,
                "status": "accepted",
            }
