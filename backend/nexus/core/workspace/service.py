"""Workspace storage business logic.

Coordinates between git storage (file content) and PostgreSQL (metadata,
embeddings, version history). This is the primary interface used by
tools and the smart context loader.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.workspace import schemas
from nexus.core.workspace.storage import (
    guess_mime_type,
    init_repo,
    is_binary_file,
    list_files as git_list_files,
    read_file as git_read_file,
    write_file as git_write_file,
)
from nexus.db.models import WorkspaceFile, WorkspaceFileVersion, WorkspaceProject
from nexus.memory.embeddings import generate_embedding
from nexus.settings import settings

logger = structlog.get_logger()

# Approximate tokens per character for budget estimation
_CHARS_PER_TOKEN = 4


async def create_project(
    session: AsyncSession,
    *,
    workspace_id: str,
    name: str,
    slug: str,
    description: str | None = None,
) -> schemas.ProjectInfo:
    """Create a new workspace project with a bare git repo.

    Args:
        session: Database session.
        workspace_id: The workspace UUID.
        name: Display name for the project.
        slug: URL-friendly identifier (unique within workspace).
        description: Optional project description.

    Returns:
        ProjectInfo with the created project metadata.
    """
    repo_path = await init_repo(workspace_id, slug)

    project = WorkspaceProject(
        id=str(uuid4()),
        workspace_id=workspace_id,
        name=name,
        slug=slug,
        description=description,
        repo_path=repo_path,
    )
    session.add(project)
    await session.flush()

    logger.info(
        "workspace_project_created",
        workspace_id=workspace_id,
        project_slug=slug,
        project_id=str(project.id),
    )

    return schemas.ProjectInfo(
        id=UUID(str(project.id)),
        workspace_id=UUID(workspace_id),
        name=name,
        slug=slug,
        description=description,
    )


async def get_project(
    session: AsyncSession,
    *,
    workspace_id: str,
    project_slug: str,
) -> WorkspaceProject | None:
    """Look up a workspace project by slug.

    Args:
        session: Database session.
        workspace_id: The workspace UUID.
        project_slug: Project slug.

    Returns:
        WorkspaceProject or None if not found.
    """
    stmt = select(WorkspaceProject).where(
        WorkspaceProject.workspace_id == workspace_id,
        WorkspaceProject.slug == project_slug,
        WorkspaceProject.is_archived.is_(False),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def write_file_with_versioning(
    session: AsyncSession,
    *,
    workspace_id: str,
    project_slug: str,
    file_path: str,
    content: str,
    commit_message: str,
    agent_id: str | None = None,
    task_id: str | None = None,
    agent_role: str = "system",
) -> schemas.WriteResult:
    """Write a file to the workspace project with full versioning.

    Creates a git commit, upserts the workspace_files row, and creates
    a workspace_file_versions row.

    Args:
        session: Database session.
        workspace_id: The workspace UUID.
        project_slug: Project slug.
        file_path: Relative file path within the project.
        content: File content as string.
        commit_message: Commit message.
        agent_id: ID of the agent making the change.
        task_id: ID of the task that triggered the change.
        agent_role: Role of the agent (for commit message prefix).

    Returns:
        WriteResult with commit details.

    Raises:
        ValueError: If project not found or file exceeds size limit.
    """
    # Validate file size
    content_bytes = len(content.encode("utf-8"))
    if content_bytes > settings.workspace_max_file_size_bytes:
        msg = (
            f"File size {content_bytes} bytes exceeds limit "
            f"{settings.workspace_max_file_size_bytes} bytes"
        )
        raise ValueError(msg)

    # Look up project
    project = await get_project(session, workspace_id=workspace_id, project_slug=project_slug)
    if project is None:
        msg = f"Project '{project_slug}' not found in workspace {workspace_id}"
        raise ValueError(msg)

    # Check file count limit
    file_count_stmt = (
        select(WorkspaceFile)
        .where(
            WorkspaceFile.project_id == str(project.id),
            WorkspaceFile.is_deleted.is_(False),
        )
    )
    file_count_result = await session.execute(file_count_stmt)
    existing_files = file_count_result.scalars().all()
    existing_file_paths = {f.file_path for f in existing_files}

    if (
        file_path not in existing_file_paths
        and len(existing_file_paths) >= settings.workspace_max_files_per_project
    ):
        msg = (
            f"Project has {len(existing_file_paths)} files, "
            f"limit is {settings.workspace_max_files_per_project}"
        )
        raise ValueError(msg)

    # Format commit message with task/agent context
    prefix_parts = []
    if task_id:
        prefix_parts.append(f"[task:{task_id}]")
    prefix_parts.append(f"[agent:{agent_role}]")
    full_commit_message = f"{' '.join(prefix_parts)} {commit_message}"

    # Write to git
    commit_sha = await git_write_file(
        workspace_id=workspace_id,
        project_slug=project_slug,
        file_path=file_path,
        content=content,
        commit_message=full_commit_message,
    )

    # Determine if this is a create or update
    existing_file_stmt = select(WorkspaceFile).where(
        WorkspaceFile.project_id == str(project.id),
        WorkspaceFile.file_path == file_path,
        WorkspaceFile.is_deleted.is_(False),
    )
    existing_result = await session.execute(existing_file_stmt)
    existing_file = existing_result.scalar_one_or_none()

    mime_type = guess_mime_type(file_path)
    binary = is_binary_file(file_path)

    if existing_file is not None:
        # Update existing file
        operation = "update"
        existing_file.size_bytes = content_bytes
        existing_file.last_commit_sha = commit_sha
        existing_file.last_modified_by_agent_id = agent_id
        existing_file.last_modified_by_task_id = task_id
        existing_file.mime_type = mime_type
        file_id = str(existing_file.id)

        # Get next version number
        version_stmt = (
            select(WorkspaceFileVersion)
            .where(WorkspaceFileVersion.file_id == file_id)
            .order_by(WorkspaceFileVersion.version_number.desc())
            .limit(1)
        )
        version_result = await session.execute(version_stmt)
        last_version = version_result.scalar_one_or_none()
        version_number = (last_version.version_number + 1) if last_version else 1
    else:
        # Create new file
        operation = "create"
        file_id = str(uuid4())
        new_file = WorkspaceFile(
            id=file_id,
            project_id=str(project.id),
            workspace_id=workspace_id,
            file_path=file_path,
            mime_type=mime_type,
            size_bytes=content_bytes,
            is_binary=binary,
            last_commit_sha=commit_sha,
            last_modified_by_agent_id=agent_id,
            last_modified_by_task_id=task_id,
        )
        session.add(new_file)
        version_number = 1

    # Create version record
    version = WorkspaceFileVersion(
        id=str(uuid4()),
        file_id=file_id,
        project_id=str(project.id),
        commit_sha=commit_sha,
        version_number=version_number,
        operation=operation,
        size_bytes=content_bytes,
        agent_id=agent_id,
        task_id=task_id,
        commit_message=full_commit_message,
    )
    session.add(version)
    await session.flush()

    logger.info(
        "workspace_file_written",
        workspace_id=workspace_id,
        project_slug=project_slug,
        file_path=file_path,
        operation=operation,
        commit_sha=commit_sha,
        version=version_number,
        agent_id=agent_id,
        task_id=task_id,
    )

    return schemas.WriteResult(
        file_id=UUID(file_id),
        file_path=file_path,
        commit_sha=commit_sha,
        version_number=version_number,
        size_bytes=content_bytes,
        operation=operation,
    )


async def read_file(
    session: AsyncSession,
    *,
    workspace_id: str,
    project_slug: str,
    file_path: str,
    version: int | None = None,
) -> str | None:
    """Read a file from the workspace project.

    Args:
        session: Database session.
        workspace_id: The workspace UUID.
        project_slug: Project slug.
        file_path: Relative file path.
        version: Optional version number. Defaults to latest.

    Returns:
        File content as string, or None if not found.
    """
    commit_sha: str | None = None

    if version is not None:
        # Look up the commit SHA for this version
        project = await get_project(
            session, workspace_id=workspace_id, project_slug=project_slug
        )
        if project is None:
            return None

        version_stmt = (
            select(WorkspaceFileVersion)
            .join(WorkspaceFile, WorkspaceFileVersion.file_id == WorkspaceFile.id)
            .where(
                WorkspaceFile.project_id == str(project.id),
                WorkspaceFile.file_path == file_path,
                WorkspaceFileVersion.version_number == version,
            )
        )
        version_result = await session.execute(version_stmt)
        version_record = version_result.scalar_one_or_none()
        if version_record is None:
            return None
        commit_sha = version_record.commit_sha

    return await git_read_file(
        workspace_id=workspace_id,
        project_slug=project_slug,
        file_path=file_path,
        commit_sha=commit_sha,
    )


async def list_project_files(
    session: AsyncSession,
    *,
    workspace_id: str,
    project_slug: str,
    path_prefix: str = "",
    include_deleted: bool = False,
) -> list[schemas.FileMetadata]:
    """List files in a workspace project from the database.

    Args:
        session: Database session.
        workspace_id: The workspace UUID.
        project_slug: Project slug.
        path_prefix: Optional prefix filter.
        include_deleted: Whether to include soft-deleted files.

    Returns:
        List of FileMetadata.
    """
    project = await get_project(
        session, workspace_id=workspace_id, project_slug=project_slug
    )
    if project is None:
        return []

    stmt = select(WorkspaceFile).where(
        WorkspaceFile.project_id == str(project.id),
    )
    if not include_deleted:
        stmt = stmt.where(WorkspaceFile.is_deleted.is_(False))
    if path_prefix:
        stmt = stmt.where(WorkspaceFile.file_path.startswith(path_prefix))

    stmt = stmt.order_by(WorkspaceFile.file_path)
    result = await session.execute(stmt)
    files = result.scalars().all()

    return [
        schemas.FileMetadata(
            id=UUID(str(f.id)),
            project_id=UUID(str(f.project_id)),
            file_path=f.file_path,
            mime_type=f.mime_type,
            size_bytes=f.size_bytes,
            is_binary=f.is_binary,
            is_deleted=f.is_deleted,
            last_commit_sha=f.last_commit_sha,
            last_modified_by_agent_id=f.last_modified_by_agent_id,
            last_modified_by_task_id=f.last_modified_by_task_id,
            content_summary=f.content_summary,
            tags=f.tags,
            created_at=f.created_at,
            updated_at=f.updated_at,
        )
        for f in files
    ]


async def search_files(
    session: AsyncSession,
    *,
    workspace_id: str,
    query: str,
    project_slug: str | None = None,
    limit: int = 10,
) -> list[schemas.SearchResult]:
    """Semantic search across workspace files using pgvector.

    Args:
        session: Database session.
        workspace_id: The workspace UUID.
        query: Search query string.
        project_slug: Optional filter to a specific project.
        limit: Maximum results to return.

    Returns:
        List of SearchResult ordered by similarity.
    """
    query_embedding = await generate_embedding(query)
    if query_embedding is None:
        logger.warning("workspace_search_no_embedding", query=query[:100])
        return []

    stmt = (
        select(
            WorkspaceFile,
            WorkspaceProject.slug,
            WorkspaceFile.embedding.cosine_distance(query_embedding).label("distance"),
        )
        .join(WorkspaceProject, WorkspaceFile.project_id == WorkspaceProject.id)
        .where(
            WorkspaceFile.workspace_id == workspace_id,
            WorkspaceFile.is_deleted.is_(False),
            WorkspaceFile.embedding.isnot(None),
        )
    )

    if project_slug:
        stmt = stmt.where(WorkspaceProject.slug == project_slug)

    stmt = stmt.order_by("distance").limit(limit)
    result = await session.execute(stmt)
    rows = result.all()

    return [
        schemas.SearchResult(
            file_path=row[0].file_path,
            content_summary=row[0].content_summary,
            similarity_score=1.0 - row[2],  # cosine_distance → similarity
            project_slug=row[1],
            size_bytes=row[0].size_bytes,
            last_modified_by_agent_id=row[0].last_modified_by_agent_id,
        )
        for row in rows
    ]


async def load_context_for_task(
    session: AsyncSession,
    *,
    workspace_id: str,
    instruction_embedding: list[float],
    agent_id: str | None = None,
    token_budget: int | None = None,
) -> schemas.WorkspaceContext:
    """Load relevant workspace files for a task using smart context.

    Algorithm:
      1. pgvector similarity search on file content summaries
      2. Filter by token budget (accumulate file sizes, stop when full)
      3. Also include last 5 files modified by this agent (working continuity)
      4. Read content from git for selected files

    Args:
        session: Database session.
        workspace_id: The workspace UUID.
        instruction_embedding: Embedding of the task instruction.
        agent_id: Optional agent ID for working continuity.
        token_budget: Max tokens for workspace context. Uses setting default.

    Returns:
        WorkspaceContext with loaded files.
    """
    budget = token_budget or settings.workspace_context_token_budget
    context = schemas.WorkspaceContext()

    # Step 1: Similarity search for relevant files
    stmt = (
        select(
            WorkspaceFile,
            WorkspaceProject.slug.label("project_slug"),
            WorkspaceProject.workspace_id,
            WorkspaceFile.embedding.cosine_distance(instruction_embedding).label("distance"),
        )
        .join(WorkspaceProject, WorkspaceFile.project_id == WorkspaceProject.id)
        .where(
            WorkspaceFile.workspace_id == workspace_id,
            WorkspaceFile.is_deleted.is_(False),
            WorkspaceFile.is_binary.is_(False),
            WorkspaceFile.embedding.isnot(None),
        )
        .order_by("distance")
        .limit(10)
    )
    result = await session.execute(stmt)
    similar_rows = result.all()

    # Step 2: Also get last 5 files modified by this agent
    recent_file_ids: set[str] = set()
    if agent_id:
        recent_stmt = (
            select(WorkspaceFile, WorkspaceProject.slug.label("project_slug"))
            .join(WorkspaceProject, WorkspaceFile.project_id == WorkspaceProject.id)
            .where(
                WorkspaceFile.workspace_id == workspace_id,
                WorkspaceFile.is_deleted.is_(False),
                WorkspaceFile.is_binary.is_(False),
                WorkspaceFile.last_modified_by_agent_id == agent_id,
            )
            .order_by(WorkspaceFile.updated_at.desc())
            .limit(5)
        )
        recent_result = await session.execute(recent_stmt)
        recent_rows = recent_result.all()
    else:
        recent_rows = []

    # Step 3: Accumulate files within token budget
    tokens_used = 0
    loaded_file_paths: set[str] = set()

    # Process similar files first, then recent files
    all_candidates: list[tuple[Any, str, float]] = []

    for row in similar_rows:
        ws_file = row[0]
        proj_slug = row[1]
        distance = row[3]
        similarity = 1.0 - distance
        all_candidates.append((ws_file, proj_slug, similarity))

    for row in recent_rows:
        ws_file = row[0]
        proj_slug = row[1]
        if ws_file.file_path not in {c[0].file_path for c in all_candidates}:
            all_candidates.append((ws_file, proj_slug, 0.5))  # default score for recent

    for ws_file, proj_slug, similarity in all_candidates:
        if ws_file.file_path in loaded_file_paths:
            continue

        estimated_tokens = ws_file.size_bytes // _CHARS_PER_TOKEN
        if tokens_used + estimated_tokens > budget:
            # Try loading summary only for large files
            if ws_file.content_summary and ws_file.size_bytes > 50_000:
                summary_tokens = len(ws_file.content_summary) // _CHARS_PER_TOKEN
                if tokens_used + summary_tokens <= budget:
                    context.files.append(
                        schemas.ContextFile(
                            file_path=ws_file.file_path,
                            content=f"[File too large — summary only]\n{ws_file.content_summary}",
                            content_summary=ws_file.content_summary,
                            size_bytes=ws_file.size_bytes,
                            similarity_score=similarity,
                        )
                    )
                    tokens_used += summary_tokens
                    loaded_file_paths.add(ws_file.file_path)
            continue

        # Read full content from git
        content = await git_read_file(
            workspace_id=workspace_id,
            project_slug=proj_slug,
            file_path=ws_file.file_path,
        )
        if content is None:
            continue

        # Truncate very large files
        if len(content) > 50_000:
            truncated = content[:2000] + "\n\n... [truncated] ...\n\n" + content[-2000:]
            content = truncated

        context.files.append(
            schemas.ContextFile(
                file_path=ws_file.file_path,
                content=content,
                content_summary=ws_file.content_summary,
                size_bytes=ws_file.size_bytes,
                similarity_score=similarity,
            )
        )
        tokens_used += estimated_tokens
        loaded_file_paths.add(ws_file.file_path)

        if not context.project_slug:
            context.project_slug = proj_slug

    context.total_tokens_used = tokens_used
    return context
