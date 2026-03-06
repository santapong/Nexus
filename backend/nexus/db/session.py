from __future__ import annotations

from advanced_alchemy.extensions.litestar import (
    AsyncSessionConfig,
    SQLAlchemyAsyncConfig,
)

from nexus.settings import settings

session_config = AsyncSessionConfig(expire_on_commit=False)

sqlalchemy_config = SQLAlchemyAsyncConfig(
    connection_string=settings.database_url,
    session_config=session_config,
    create_all=False,  # Alembic handles schema
)
