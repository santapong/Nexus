"""Row-Level Security session context for multi-tenant workspace isolation.

Sets `nexus.workspace_id` as a PostgreSQL session variable via `SET LOCAL`
at the start of every database session within a request. This ensures all
queries are automatically filtered by the RLS policies defined in migration 006.

Usage in Litestar middleware:
    The RLSMiddleware extracts workspace_id from the JWT and calls
    `set_rls_context()` on the session before any query executes.

For background tasks (agents, Taskiq workers):
    Use `rls_session()` context manager with an explicit workspace_id.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.session import get_session_factory

logger = structlog.get_logger()


async def set_rls_context(session: AsyncSession, workspace_id: str) -> None:
    """Set the RLS workspace context for the current database transaction.

    Must be called within an active transaction (session.begin() or autobegin).
    Uses SET LOCAL so the setting is scoped to the current transaction only.

    Args:
        session: Active async database session.
        workspace_id: Workspace UUID string, or 'superuser' for admin access.
    """
    await session.execute(
        text("SET LOCAL nexus.workspace_id = :ws_id"),
        {"ws_id": workspace_id},
    )


async def clear_rls_context(session: AsyncSession) -> None:
    """Reset the RLS workspace context to empty.

    Args:
        session: Active async database session.
    """
    await session.execute(text("RESET nexus.workspace_id"))


@asynccontextmanager
async def rls_session(workspace_id: str) -> AsyncGenerator[AsyncSession, None]:
    """Create a database session with RLS workspace context pre-configured.

    For use in background tasks, agents, and Taskiq workers that run
    outside the Litestar request lifecycle.

    Args:
        workspace_id: Workspace UUID string, or 'superuser' for admin.

    Yields:
        AsyncSession with RLS context set.
    """
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_context(session, workspace_id)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
