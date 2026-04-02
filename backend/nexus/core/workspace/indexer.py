"""File content indexer — generates LLM summaries and pgvector embeddings.

When a file is written to the workspace, the indexer:
  1. Generates a 2-3 sentence summary of the file content using the LLM
  2. Embeds the summary via Google embedding-001
  3. Updates the workspace_files row with summary + embedding

This runs asynchronously after the write completes — it does NOT block
the write path.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.workspace.storage import is_binary_file, read_file as git_read_file
from nexus.db.models import WorkspaceFile, WorkspaceProject
from nexus.memory.embeddings import generate_embedding
from nexus.settings import settings

logger = structlog.get_logger()

# Max content length to send to LLM for summarization
_MAX_CONTENT_FOR_SUMMARY = 10_000

# Fallback summary when LLM is unavailable
_FALLBACK_SUMMARY_TEMPLATE = "File: {file_path} ({size_bytes} bytes, {mime_type})"


async def index_file(
    session: AsyncSession,
    *,
    file_id: str,
    workspace_id: str,
    project_slug: str,
) -> None:
    """Generate summary and embedding for a workspace file.

    Args:
        session: Database session.
        file_id: The workspace_files row ID.
        workspace_id: The workspace UUID.
        project_slug: Project slug for git access.
    """
    # Load the file record
    stmt = select(WorkspaceFile).where(WorkspaceFile.id == file_id)
    result = await session.execute(stmt)
    ws_file = result.scalar_one_or_none()

    if ws_file is None:
        logger.warning("index_file_not_found", file_id=file_id)
        return

    # Skip binary files
    if ws_file.is_binary or is_binary_file(ws_file.file_path):
        logger.info(
            "index_file_skipped_binary",
            file_id=file_id,
            file_path=ws_file.file_path,
        )
        return

    # Read content from git
    content = await git_read_file(
        workspace_id=workspace_id,
        project_slug=project_slug,
        file_path=ws_file.file_path,
    )
    if content is None:
        logger.warning(
            "index_file_content_not_found",
            file_id=file_id,
            file_path=ws_file.file_path,
        )
        return

    # Generate summary
    summary = await _generate_summary(ws_file.file_path, content, ws_file.mime_type)
    ws_file.content_summary = summary

    # Generate embedding from summary
    embedding = await generate_embedding(summary)
    if embedding is not None:
        ws_file.embedding = embedding

    await session.flush()

    logger.info(
        "workspace_file_indexed",
        file_id=file_id,
        file_path=ws_file.file_path,
        has_embedding=embedding is not None,
        summary_length=len(summary),
    )


async def _generate_summary(
    file_path: str,
    content: str,
    mime_type: str | None,
) -> str:
    """Generate a concise summary of file content.

    Uses the LLM to produce a 2-3 sentence summary. Falls back to a
    metadata-based summary if the LLM is unavailable.

    Args:
        file_path: Relative file path.
        content: File content.
        mime_type: MIME type.

    Returns:
        Summary string.
    """
    # Truncate content for the LLM
    truncated_content = content[:_MAX_CONTENT_FOR_SUMMARY]
    if len(content) > _MAX_CONTENT_FOR_SUMMARY:
        truncated_content += "\n... [content truncated]"

    # Try LLM summarization
    try:
        from pydantic_ai import Agent as PydanticAgent

        from nexus.core.llm.factory import ModelFactory
        from nexus.db.models import AgentRole

        model = ModelFactory.get_model(AgentRole.QA)  # Use cheapest model
        summarizer = PydanticAgent(
            model,
            system_prompt=(
                "You are a file content summarizer. Given a file path and its content, "
                "produce a 2-3 sentence summary describing what the file contains, "
                "its purpose, and key elements. Be specific and technical. "
                "Do NOT include the file path in the summary."
            ),
        )

        prompt = f"File: {file_path}\nMIME type: {mime_type or 'unknown'}\n\nContent:\n{truncated_content}"
        result = await summarizer.run(prompt)
        return result.output

    except Exception:
        logger.warning(
            "index_file_summary_fallback",
            file_path=file_path,
            exc_info=True,
        )
        # Fallback: metadata-based summary
        return _FALLBACK_SUMMARY_TEMPLATE.format(
            file_path=file_path,
            size_bytes=len(content),
            mime_type=mime_type or "unknown",
        )


async def reindex_project(
    session: AsyncSession,
    *,
    workspace_id: str,
    project_slug: str,
) -> int:
    """Re-index all files in a workspace project.

    Useful after bulk imports or when embeddings need regenerating.

    Args:
        session: Database session.
        workspace_id: The workspace UUID.
        project_slug: Project slug.

    Returns:
        Number of files indexed.
    """
    project_stmt = select(WorkspaceProject).where(
        WorkspaceProject.workspace_id == workspace_id,
        WorkspaceProject.slug == project_slug,
    )
    project_result = await session.execute(project_stmt)
    project = project_result.scalar_one_or_none()

    if project is None:
        return 0

    files_stmt = select(WorkspaceFile).where(
        WorkspaceFile.project_id == str(project.id),
        WorkspaceFile.is_deleted.is_(False),
        WorkspaceFile.is_binary.is_(False),
    )
    files_result = await session.execute(files_stmt)
    files = files_result.scalars().all()

    indexed = 0
    for ws_file in files:
        await index_file(
            session,
            file_id=str(ws_file.id),
            workspace_id=workspace_id,
            project_slug=project_slug,
        )
        indexed += 1

    logger.info(
        "workspace_project_reindexed",
        workspace_id=workspace_id,
        project_slug=project_slug,
        files_indexed=indexed,
    )
    return indexed
