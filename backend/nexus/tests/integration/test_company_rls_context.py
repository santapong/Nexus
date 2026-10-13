"""Actual PostgreSQL transaction-local scope and propagated injection faults.

The dedicated disposable scope-test DB is mandatory. These checks fix the
parameter binding boundary; they do not validate the broken legacy migrations.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import Mock

import pytest
from sqlalchemy import Connection, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from nexus.api import middleware
from nexus.db.rls import set_rls_context
from nexus.settings import settings

SCOPE = "a2150a55-c9e6-44dd-a2ee-d6974e3cf0b1"
INJECTION = "workspace'; SELECT set_config('nexus.scope_probe', 'changed', false); --"


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """Reuse one physical connection, demonstrating pool scope cannot leak between work."""
    if not settings.company_test_database_url:
        pytest.skip("Explicit disposable company scope-test DB is not configured")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_rls_scope"
    assert settings.company_test_database_url != settings.database_url
    resource = create_async_engine(url, pool_size=1, max_overflow=0)
    try:
        yield resource
    finally:
        await resource.dispose()


async def current_scope(session: AsyncSession) -> str | None:
    """Normalize PostgreSQL's unset and reset custom-GUC representations."""
    return await session.scalar(
        select(func.nullif(func.current_setting("nexus.workspace_id", True), ""))
    )


@pytest.mark.parametrize("mechanism", ["hook", "helper"])
@pytest.mark.parametrize("boundary", ["commit", "rollback"])
@pytest.mark.parametrize("value", [SCOPE, INJECTION])
async def test_real_workspace_context_is_local_and_injection_remains_a_value(
    engine: AsyncEngine, mechanism: str, boundary: str, value: str
) -> None:
    """Read actual server state before/during/after each production context setter."""
    async with AsyncSession(engine) as session:
        assert await current_scope(session) is None
        backend_pid = await session.scalar(select(func.pg_backend_pid()))
        await session.rollback()
        token = middleware._workspace_id_ctx.set(value if mechanism == "hook" else None)
        try:
            if mechanism == "helper":
                await set_rls_context(session, value)
            assert await current_scope(session) == value
            assert (
                await session.scalar(select(func.current_setting("nexus.scope_probe", True)))
                is None
            )
            if boundary == "commit":
                await session.commit()
            else:
                await session.rollback()
        finally:
            middleware._workspace_id_ctx.reset(token)
    async with AsyncSession(engine) as subsequent:
        assert await subsequent.scalar(select(func.pg_backend_pid())) == backend_pid
        assert await current_scope(subsequent) is None
        assert (
            await subsequent.scalar(select(func.current_setting("nexus.scope_probe", True))) is None
        )


def call_hook(connection: Connection) -> None:
    """Exercise the hook directly with real SQL, isolating its exception semantics."""
    with Session() as session:
        middleware._inject_rls_workspace(session, None, connection)


async def test_real_hook_failure_is_logged_and_propagated(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PostgreSQL rejects a NUL text value; swallowing this error is forbidden."""
    warning = Mock()
    monkeypatch.setattr(middleware.logger, "warning", warning)
    token = middleware._workspace_id_ctx.set("scope\x00invalid")
    try:
        async with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                await connection.run_sync(call_hook)
            await connection.rollback()
    finally:
        middleware._workspace_id_ctx.reset(token)
    warning.assert_called_once()


async def test_real_helper_propagates_invalid_text_and_rollback_clears_scope(
    engine: AsyncEngine,
) -> None:
    async with AsyncSession(engine) as session:
        with pytest.raises(DBAPIError):
            await set_rls_context(session, "scope\x00invalid")
        await session.rollback()
        assert await current_scope(session) is None


async def test_without_request_context_hook_does_not_set_a_workspace(
    engine: AsyncEngine,
) -> None:
    token = middleware._workspace_id_ctx.set(None)
    try:
        async with AsyncSession(engine) as session:
            assert await current_scope(session) is None
    finally:
        middleware._workspace_id_ctx.reset(token)
