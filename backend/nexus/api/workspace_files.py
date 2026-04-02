"""REST API for workspace file management.

Provides endpoints for browsing, reading, searching, and viewing
file history within workspace projects.
"""

from __future__ import annotations

from typing import Any

import structlog
from litestar import Controller, Response, get, post
from litestar.di import Provide
from litestar.params import Parameter
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.workspace.schemas import (
    FileMetadata,
    FileVersion,
    ProjectInfo,
    SearchResult,
)
from nexus.core.workspace.service import (
    create_project,
    get_project,
    list_project_files,
    read_file,
    search_files,
)

logger = structlog.get_logger()


class WorkspaceFileController(Controller):
    """Workspace file management endpoints."""

    path = "/workspaces/{workspace_id:str}/projects"

    @get("/", summary="List projects in workspace")
    async def list_projects(
        self,
        workspace_id: str,
        db_session: AsyncSession,
    ) -> list[dict[str, Any]]:
        """List all projects in a workspace."""
        from sqlalchemy import select
        from nexus.db.models import WorkspaceProject

        stmt = select(WorkspaceProject).where(
            WorkspaceProject.workspace_id == workspace_id,
            WorkspaceProject.is_archived.is_(False),
        ).order_by(WorkspaceProject.name)
        result = await db_session.execute(stmt)
        projects = result.scalars().all()

        return [
            {
                "id": str(p.id),
                "name": p.name,
                "slug": p.slug,
                "description": p.description,
                "default_branch": p.default_branch,
                "is_archived": p.is_archived,
                "created_at": str(p.created_at),
            }
            for p in projects
        ]

    @post("/", summary="Create a new project")
    async def create_project_endpoint(
        self,
        workspace_id: str,
        db_session: AsyncSession,
        data: dict[str, Any],
    ) -> ProjectInfo:
        """Create a new workspace project with a git repository."""
        project = await create_project(
            db_session,
            workspace_id=workspace_id,
            name=data["name"],
            slug=data["slug"],
            description=data.get("description"),
        )
        await db_session.commit()
        return project

    @get("/{project_slug:str}/files", summary="List files in project")
    async def list_files(
        self,
        workspace_id: str,
        project_slug: str,
        db_session: AsyncSession,
        path_prefix: str = Parameter(default="", query="path_prefix"),
        include_deleted: bool = Parameter(default=False, query="include_deleted"),
    ) -> list[FileMetadata]:
        """List files in a workspace project."""
        return await list_project_files(
            db_session,
            workspace_id=workspace_id,
            project_slug=project_slug,
            path_prefix=path_prefix,
            include_deleted=include_deleted,
        )

    @get("/{project_slug:str}/files/{file_path:path}", summary="Read file content")
    async def read_file_endpoint(
        self,
        workspace_id: str,
        project_slug: str,
        file_path: str,
        db_session: AsyncSession,
        version: int | None = Parameter(default=None, query="version"),
    ) -> Response:
        """Read file content from a workspace project."""
        content = await read_file(
            db_session,
            workspace_id=workspace_id,
            project_slug=project_slug,
            file_path=file_path,
            version=version,
        )

        if content is None:
            return Response(
                content={"error": f"File not found: {file_path}"},
                status_code=404,
            )

        return Response(
            content={"file_path": file_path, "content": content, "version": version},
            status_code=200,
        )

    @get(
        "/{project_slug:str}/files/{file_path:path}/history",
        summary="Get file version history",
    )
    async def file_history(
        self,
        workspace_id: str,
        project_slug: str,
        file_path: str,
        db_session: AsyncSession,
    ) -> list[FileVersion]:
        """Get version history for a specific file."""
        from sqlalchemy import select
        from nexus.db.models import WorkspaceFile, WorkspaceFileVersion

        project = await get_project(
            db_session, workspace_id=workspace_id, project_slug=project_slug
        )
        if project is None:
            return []

        stmt = (
            select(WorkspaceFileVersion)
            .join(WorkspaceFile, WorkspaceFileVersion.file_id == WorkspaceFile.id)
            .where(
                WorkspaceFile.project_id == str(project.id),
                WorkspaceFile.file_path == file_path,
            )
            .order_by(WorkspaceFileVersion.version_number.desc())
        )
        result = await db_session.execute(stmt)
        versions = result.scalars().all()

        return [
            FileVersion(
                id=v.id,
                file_id=v.file_id,
                commit_sha=v.commit_sha,
                version_number=v.version_number,
                operation=v.operation,
                size_bytes=v.size_bytes,
                diff_summary=v.diff_summary,
                agent_id=v.agent_id,
                task_id=v.task_id,
                commit_message=v.commit_message,
                created_at=v.created_at,
            )
            for v in versions
        ]

    @get("/{project_slug:str}/search", summary="Search files by content")
    async def search_files_endpoint(
        self,
        workspace_id: str,
        project_slug: str,
        db_session: AsyncSession,
        q: str = Parameter(query="q"),
        limit: int = Parameter(default=10, query="limit"),
    ) -> list[SearchResult]:
        """Semantic search across project files."""
        return await search_files(
            db_session,
            workspace_id=workspace_id,
            query=q,
            project_slug=project_slug,
            limit=limit,
        )
