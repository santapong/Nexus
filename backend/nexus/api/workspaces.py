"""Workspace and auth API — user registration, login, workspace management.

Endpoints:
- POST /api/auth/register  — Register a new user + default workspace
- POST /api/auth/login     — Login and get JWT token
- GET  /api/workspaces     — List user's workspaces
- POST /api/workspaces     — Create a new workspace
- GET  /api/workspaces/{id} — Get workspace details
"""
from __future__ import annotations

from typing import Any

import structlog
from litestar import Controller, get, post
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.auth import (
    AuthUser,
    create_access_token,
    get_auth_user_from_request,
    hash_password,
    verify_password,
)
from nexus.db.models import User, Workspace, WorkspaceMember

logger = structlog.get_logger()


# ─── Request/Response schemas ────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    """User registration request."""

    email: str
    password: str
    display_name: str


class LoginRequest(BaseModel):
    """User login request."""

    email: str
    password: str


class RegisterResponse(BaseModel):
    """Registration response with JWT token."""

    user_id: str
    workspace_id: str
    access_token: str


class LoginResponse(BaseModel):
    """Login response with JWT token and user info."""

    access_token: str
    user: AuthUser


class WorkspaceResponse(BaseModel):
    """Workspace details."""

    id: str
    name: str
    slug: str
    owner_id: str
    is_active: bool
    daily_spend_limit_usd: float


class CreateWorkspaceRequest(BaseModel):
    """Request to create a new workspace."""

    name: str
    slug: str


# ─── Auth Controller ─────────────────────────────────────────────────────────


class AuthController(Controller):
    """User authentication endpoints."""

    path = "/auth"

    @post("/register")
    async def register(
        self,
        data: RegisterRequest,
        db_session: AsyncSession,
    ) -> RegisterResponse:
        """Register a new user with a default workspace.

        Args:
            data: Registration details (email, password, display_name).
            db_session: Async database session.

        Returns:
            RegisterResponse with user_id, workspace_id, and JWT token.
        """
        # Check if email already exists
        stmt = select(User).where(User.email == data.email)
        result = await db_session.execute(stmt)
        if result.scalar_one_or_none() is not None:
            return RegisterResponse(
                user_id="", workspace_id="", access_token=""
            )

        # Create user
        user = User(
            email=data.email,
            password_hash=hash_password(data.password),
            display_name=data.display_name,
        )
        db_session.add(user)
        await db_session.flush()

        # Create default workspace
        slug = data.email.split("@")[0].lower().replace(".", "-")
        workspace = Workspace(
            name=f"{data.display_name}'s Company",
            slug=slug,
            owner_id=str(user.id),
        )
        db_session.add(workspace)
        await db_session.flush()

        # Add user as workspace owner
        member = WorkspaceMember(
            workspace_id=str(workspace.id),
            user_id=str(user.id),
            role="owner",
        )
        db_session.add(member)
        await db_session.commit()

        token = create_access_token(
            user_id=str(user.id),
            workspace_id=str(workspace.id),
            email=data.email,
        )

        logger.info(
            "user_registered",
            user_id=str(user.id),
            workspace_id=str(workspace.id),
        )

        return RegisterResponse(
            user_id=str(user.id),
            workspace_id=str(workspace.id),
            access_token=token,
        )

    @post("/login")
    async def login(
        self,
        data: LoginRequest,
        db_session: AsyncSession,
    ) -> LoginResponse:
        """Authenticate a user and return a JWT token.

        Args:
            data: Login credentials (email, password).
            db_session: Async database session.

        Returns:
            LoginResponse with JWT token and user details.
        """
        stmt = select(User).where(User.email == data.email)
        result = await db_session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None or not verify_password(data.password, user.password_hash):
            return LoginResponse(
                access_token="",
                user=AuthUser(user_id="", workspace_id="", email=""),
            )

        # Get first workspace
        ws_stmt = select(Workspace).where(Workspace.owner_id == str(user.id))
        ws_result = await db_session.execute(ws_stmt)
        workspace = ws_result.scalar_one_or_none()
        workspace_id = str(workspace.id) if workspace else ""

        token = create_access_token(
            user_id=str(user.id),
            workspace_id=workspace_id,
            email=data.email,
        )

        logger.info("user_logged_in", user_id=str(user.id))

        return LoginResponse(
            access_token=token,
            user=AuthUser(
                user_id=str(user.id),
                workspace_id=workspace_id,
                email=data.email,
            ),
        )


# ─── Workspace Controller ───────────────────────────────────────────────────


class WorkspaceController(Controller):
    """Workspace management endpoints."""

    path = "/workspaces"

    @get()
    async def list_workspaces(
        self, db_session: AsyncSession
    ) -> list[WorkspaceResponse]:
        """List all workspaces (for the current user in multi-tenant mode)."""
        stmt = select(Workspace).where(Workspace.is_active.is_(True))
        result = await db_session.execute(stmt)
        workspaces = result.scalars().all()

        return [
            WorkspaceResponse(
                id=str(ws.id),
                name=ws.name,
                slug=ws.slug,
                owner_id=str(ws.owner_id),
                is_active=ws.is_active,
                daily_spend_limit_usd=ws.daily_spend_limit_usd,
            )
            for ws in workspaces
        ]

    @post()
    async def create_workspace(
        self,
        data: CreateWorkspaceRequest,
        db_session: AsyncSession,
    ) -> WorkspaceResponse:
        """Create a new workspace."""
        workspace = Workspace(
            name=data.name,
            slug=data.slug,
            owner_id="system",  # Will be set from JWT in production
        )
        db_session.add(workspace)
        await db_session.flush()
        await db_session.commit()

        logger.info("workspace_created", workspace_id=str(workspace.id))

        return WorkspaceResponse(
            id=str(workspace.id),
            name=workspace.name,
            slug=workspace.slug,
            owner_id=str(workspace.owner_id),
            is_active=workspace.is_active,
            daily_spend_limit_usd=workspace.daily_spend_limit_usd,
        )

    @get("/{workspace_id:str}")
    async def get_workspace(
        self, workspace_id: str, db_session: AsyncSession
    ) -> WorkspaceResponse:
        """Get workspace details by ID."""
        stmt = select(Workspace).where(Workspace.id == workspace_id)
        result = await db_session.execute(stmt)
        ws = result.scalar_one_or_none()

        if ws is None:
            return WorkspaceResponse(
                id=workspace_id,
                name="Not Found",
                slug="",
                owner_id="",
                is_active=False,
                daily_spend_limit_usd=0,
            )

        return WorkspaceResponse(
            id=str(ws.id),
            name=ws.name,
            slug=ws.slug,
            owner_id=str(ws.owner_id),
            is_active=ws.is_active,
            daily_spend_limit_usd=ws.daily_spend_limit_usd,
        )
