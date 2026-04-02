"""Workspace storage tools for agents.

Four tools that give agents persistent, versioned file access:
  - tool_workspace_list: List files in a project (read-only)
  - tool_workspace_read: Read file content (read-only)
  - tool_workspace_write: Write file with git commit (irreversible)
  - tool_workspace_search: Semantic search across files (read-only)
"""

from __future__ import annotations

import structlog

from nexus.core.workspace.service import (
    list_project_files,
    read_file,
    search_files,
    write_file_with_versioning,
)
from nexus.core.workspace.indexer import index_file
from nexus.settings import settings

logger = structlog.get_logger()


async def tool_workspace_list(
    project_slug: str,
    path_prefix: str = "",
    include_deleted: bool = False,
) -> str:
    """List files in a workspace project.

    Args:
        project_slug: The project identifier (URL-friendly slug).
        path_prefix: Optional prefix to filter file paths (e.g. "src/").
        include_deleted: Whether to include soft-deleted files.

    Returns:
        Formatted list of files with sizes and metadata.
    """
    from nexus.db.session import async_session_factory

    async with async_session_factory() as session:
        files = await list_project_files(
            session,
            workspace_id=_get_workspace_id(),
            project_slug=project_slug,
            path_prefix=path_prefix,
            include_deleted=include_deleted,
        )

    if not files:
        return f"No files found in project '{project_slug}'" + (
            f" with prefix '{path_prefix}'" if path_prefix else ""
        )

    lines = [f"Files in project '{project_slug}' ({len(files)} total):"]
    for f in files:
        status = " [deleted]" if f.is_deleted else ""
        binary = " [binary]" if f.is_binary else ""
        lines.append(f"  {f.file_path} ({f.size_bytes:,} bytes){binary}{status}")

    return "\n".join(lines)


async def tool_workspace_read(
    project_slug: str,
    file_path: str,
    version: int | None = None,
) -> str:
    """Read a file from the workspace project.

    Args:
        project_slug: The project identifier.
        file_path: Relative path of the file within the project.
        version: Optional version number. Reads the latest version if omitted.

    Returns:
        File content as text, or error message if not found.
    """
    from nexus.db.session import async_session_factory

    async with async_session_factory() as session:
        content = await read_file(
            session,
            workspace_id=_get_workspace_id(),
            project_slug=project_slug,
            file_path=file_path,
            version=version,
        )

    if content is None:
        version_str = f" (version {version})" if version else ""
        return f"File not found: {file_path}{version_str} in project '{project_slug}'"

    # Truncate if too large
    max_bytes = settings.tool_file_read_max_bytes
    if len(content) > max_bytes:
        content = content[:max_bytes] + f"\n... [truncated at {max_bytes:,} bytes]"

    return content


async def tool_workspace_write(
    project_slug: str,
    file_path: str,
    content: str,
    commit_message: str,
) -> str:
    """Write a file to the workspace project. Creates a git commit.

    This is an irreversible operation that requires human approval.
    The file is persisted in a versioned git repository with full
    history tracking.

    Args:
        project_slug: The project identifier.
        file_path: Relative path for the file within the project.
        content: The file content to write.
        commit_message: Description of the change for the git commit.

    Returns:
        Confirmation with commit SHA and version number.
    """
    from nexus.db.session import async_session_factory

    workspace_id = _get_workspace_id()

    async with async_session_factory() as session:
        result = await write_file_with_versioning(
            session,
            workspace_id=workspace_id,
            project_slug=project_slug,
            file_path=file_path,
            content=content,
            commit_message=commit_message,
        )

        # Trigger async indexing (non-blocking)
        try:
            await index_file(
                session,
                file_id=str(result.file_id),
                workspace_id=workspace_id,
                project_slug=project_slug,
            )
        except Exception:
            logger.warning(
                "workspace_write_index_failed",
                file_path=file_path,
                exc_info=True,
            )

        await session.commit()

    return (
        f"File {result.operation}d: {file_path}\n"
        f"Commit: {result.commit_sha[:12]}\n"
        f"Version: {result.version_number}\n"
        f"Size: {result.size_bytes:,} bytes"
    )


async def tool_workspace_search(
    query: str,
    project_slug: str | None = None,
    limit: int = 5,
) -> str:
    """Search for files in the workspace using semantic similarity.

    Finds files whose content is most relevant to the search query
    using AI-powered embeddings.

    Args:
        query: Natural language search query describing what you're looking for.
        project_slug: Optional project to limit search to.
        limit: Maximum number of results (default 5).

    Returns:
        Ranked list of matching files with summaries and relevance scores.
    """
    from nexus.db.session import async_session_factory

    async with async_session_factory() as session:
        results = await search_files(
            session,
            workspace_id=_get_workspace_id(),
            query=query,
            project_slug=project_slug,
            limit=limit,
        )

    if not results:
        return f"No matching files found for query: '{query}'"

    lines = [f"Search results for '{query}' ({len(results)} matches):"]
    for i, r in enumerate(results, 1):
        lines.append(f"\n{i}. {r.file_path} (project: {r.project_slug})")
        lines.append(f"   Relevance: {r.similarity_score:.2%}")
        lines.append(f"   Size: {r.size_bytes:,} bytes")
        if r.content_summary:
            lines.append(f"   Summary: {r.content_summary[:200]}")

    return "\n".join(lines)


def _get_workspace_id() -> str:
    """Get the current workspace ID from context.

    In production, this would come from the task context or dependency
    injection. For now, returns a placeholder that tools can override.

    Returns:
        Workspace UUID string.
    """
    # This will be injected via RunContext in the Pydantic AI tool call.
    # For standalone use, check environment or use default.
    import os
    return os.environ.get("NEXUS_DEFAULT_WORKSPACE_ID", "default")
