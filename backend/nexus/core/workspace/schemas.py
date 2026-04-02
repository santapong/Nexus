"""Pydantic boundary models for workspace storage.

All data crossing module boundaries uses these models — no raw dicts.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectInfo(BaseModel):
    """Workspace project metadata."""

    id: UUID
    workspace_id: UUID
    name: str
    slug: str
    description: str | None = None
    default_branch: str = "main"
    is_archived: bool = False


class FileMetadata(BaseModel):
    """File metadata from workspace_files table."""

    id: UUID
    project_id: UUID
    file_path: str
    mime_type: str | None = None
    size_bytes: int
    is_binary: bool = False
    is_deleted: bool = False
    last_commit_sha: str
    last_modified_by_agent_id: str | None = None
    last_modified_by_task_id: str | None = None
    content_summary: str | None = None
    tags: list[str] | None = None
    created_at: datetime
    updated_at: datetime


class FileVersion(BaseModel):
    """Single version of a workspace file."""

    id: UUID
    file_id: UUID
    commit_sha: str
    version_number: int
    operation: str  # create | update | delete
    size_bytes: int
    diff_summary: str | None = None
    agent_id: str | None = None
    task_id: str | None = None
    commit_message: str
    created_at: datetime


class WriteResult(BaseModel):
    """Result of a workspace file write operation."""

    file_id: UUID
    file_path: str
    commit_sha: str
    version_number: int
    size_bytes: int
    operation: str  # create | update


class ContextFile(BaseModel):
    """A file loaded into agent context by the smart context system."""

    file_path: str
    content: str
    content_summary: str | None = None
    size_bytes: int
    similarity_score: float = 0.0


class WorkspaceContext(BaseModel):
    """Workspace files context returned by smart context loading."""

    project_slug: str | None = None
    files: list[ContextFile] = Field(default_factory=list)
    total_tokens_used: int = 0


class SearchResult(BaseModel):
    """A file matching a semantic search query."""

    file_path: str
    content_summary: str | None = None
    similarity_score: float
    project_slug: str
    size_bytes: int
    last_modified_by_agent_id: str | None = None
