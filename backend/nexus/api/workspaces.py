"""Workspace and auth API — user registration, login, workspace management.

Endpoints:
- POST /api/auth/register  — Register a new user + default workspace
- POST /api/auth/login     — Login and get JWT token
- GET  /api/workspaces     — List user's workspaces
- POST /api/workspaces     — Create a new workspace
- GET  /api/workspaces/{id} — Get workspace details
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from litestar import Controller, Request, get, post
from pydantic import BaseModel
from sqlalchemy import exists, select
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

_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")


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


# ─── Helpers ────────────────────────────────────────────────────────────────


async def _generate_unique_slug(base: str, db_session: AsyncSession) -> str:
    """Generate a unique slug, appending -N suffix on collision.

    Args:
        base: Base slug string (already sanitized).
        db_session: Async database session.

    Returns:
        A unique slug string.
    """
    slug = base
    counter = 1
    while True:
        stmt = select(
            exists().where(Workspace.slug == slug)
        )
        result = await db_session.execute(stmt)
        if not result.scalar():
            return slug
        slug = f"{base}-{counter}"
        counter += 1
        if counter > 100:
            # Safety valve — use UUID suffix
            import uuid

            return f"{base}-{uuid.uuid4().hex[:8]}"


def _sanitize_slug(raw: str) -> str:
    """Sanitize a raw string into a valid slug.

    Args:
        raw: Raw input (e.g. email prefix).

    Returns:
        Lowercase alphanumeric slug with hyphens.
    """
    slug = re.sub(r"[^a-z0-9-]", "-", raw.lower().strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    if len(slug) < 3:
        slug = slug + "-workspace"
    if len(slug) > 50:
        slug = slug[:50].rstrip("-")
    return slug


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
            return RegisterResponse(user_id="", workspace_id="", access_token="")

        # Create user
        user = User(
            email=data.email,
            password_hash=hash_password(data.password),
            display_name=data.display_name,
        )
        db_session.add(user)
        await db_session.flush()

        # Create default workspace with unique slug
        base_slug = _sanitize_slug(data.email.split("@")[0])
        slug = await _generate_unique_slug(base_slug, db_session)
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
        self,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
    ) -> list[WorkspaceResponse]:
        """List workspaces the authenticated user is a member of."""
        auth_user = get_auth_user_from_request(request)
        if auth_user is None:
            return []

        stmt = (
            select(Workspace)
            .join(WorkspaceMember, Workspace.id == WorkspaceMember.workspace_id)
            .where(
                WorkspaceMember.user_id == auth_user.user_id,
                Workspace.is_active.is_(True),
            )
        )
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
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
    ) -> WorkspaceResponse | dict[str, str]:
        """Create a new workspace for the authenticated user."""
        auth_user = get_auth_user_from_request(request)
        if auth_user is None:
            return {"error": "Authentication required"}

        # Validate slug
        sanitized_slug = _sanitize_slug(data.slug)
        if not _SLUG_PATTERN.match(sanitized_slug):
            return {"error": "Invalid slug. Use 3-50 lowercase alphanumeric chars and hyphens."}

        slug = await _generate_unique_slug(sanitized_slug, db_session)

        workspace = Workspace(
            name=data.name,
            slug=slug,
            owner_id=auth_user.user_id,
        )
        db_session.add(workspace)
        await db_session.flush()

        # Add creator as owner
        member = WorkspaceMember(
            workspace_id=str(workspace.id),
            user_id=auth_user.user_id,
            role="owner",
        )
        db_session.add(member)
        await db_session.commit()

        logger.info(
            "workspace_created",
            workspace_id=str(workspace.id),
            owner_id=auth_user.user_id,
        )

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
        self,
        workspace_id: str,
        request: Request[Any, Any, Any],
        db_session: AsyncSession,
    ) -> WorkspaceResponse | dict[str, str]:
        """Get workspace details by ID. User must be a member."""
        auth_user = get_auth_user_from_request(request)
        if auth_user is None:
            return {"error": "Authentication required"}

        # Verify membership
        member_stmt = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == auth_user.user_id,
        )
        member_result = await db_session.execute(member_stmt)
        if member_result.scalar_one_or_none() is None:
            return {"error": "Workspace not found"}

        stmt = select(Workspace).where(Workspace.id == workspace_id)
        result = await db_session.execute(stmt)
        ws = result.scalar_one_or_none()

        if ws is None:
            return {"error": "Workspace not found"}

        return WorkspaceResponse(
            id=str(ws.id),
            name=ws.name,
            slug=ws.slug,
            owner_id=str(ws.owner_id),
            is_active=ws.is_active,
            daily_spend_limit_usd=ws.daily_spend_limit_usd,
        )
