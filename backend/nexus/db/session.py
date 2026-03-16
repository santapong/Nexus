"""Database session configuration with connection pooling.

Uses Advanced Alchemy with production-ready pool settings:
- pool_pre_ping validates connections before use
- pool_size + max_overflow prevent connection exhaustion
- pool_recycle prevents stale connections
"""
from __future__ import annotations

from advanced_alchemy.extensions.litestar import (
    AsyncSessionConfig,
    SQLAlchemyAsyncConfig,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.settings import settings

session_config = AsyncSessionConfig(expire_on_commit=False)

sqlalchemy_config = SQLAlchemyAsyncConfig(
    connection_string=settings.database_url,
    session_config=session_config,
    create_all=False,  # Alembic handles schema
    engine_config={
        "pool_pre_ping": True,       # Validate connections before use
        "pool_size": 10,             # Persistent connections in pool
        "max_overflow": 20,          # Extra connections under load
        "pool_recycle": 3600,        # Recycle connections after 1 hour
        "pool_timeout": 30,          # Wait max 30s for a connection
        "echo": False,
    },
)


def get_session_factory() -> async_sessionmaker:
    """Create a standalone session factory for background tasks.

    Used by eval runner, dead letter publisher, and other code
    that runs outside the Litestar request lifecycle.

    Returns:
        An async session factory bound to the configured engine.
    """
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=3600,
    )
    return async_sessionmaker(engine, expire_on_commit=False)
