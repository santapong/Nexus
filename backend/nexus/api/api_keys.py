"""Workspace API key management — programmatic access.

Allows workspace owners to create API keys for programmatic task submission.
Keys are scoped by permission level: read-only, task-submit, or admin.

All route handlers receive `db_session` via Litestar dependency injection
from the SQLAlchemy plugin. This ensures every query runs through the
request-scoped session that RLSMiddleware has annotated with the caller's
`nexus.workspace_id` — bypassing it would defeat row-level security and
let any caller list/create/revoke keys across tenants.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from litestar import Controller, delete, get, post
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import ApiKey

logger = structlog.get_logger()

_KEY_PREFIX = "nxs_"
_KEY_LENGTH = 48


def _generate_api_key() -> tuple[str, str]:
    """Generate an API key and its hash.

    Returns:
        Tuple of (raw_key, hashed_key). Raw key is shown once to the user.
    """
    raw_key = _KEY_PREFIX + secrets.token_urlsafe(_KEY_LENGTH)
    hashed = hashlib.sha256(raw_key.encode()).hexdigest()
    return raw_key, hashed


class ApiKeyController(Controller):
    path = "/api/workspaces/{workspace_id:uuid}/api-keys"

    @post("/")
    async def create_api_key(
        self,
        workspace_id: UUID,
        data: dict[str, Any],
        db_session: AsyncSession,
    ) -> dict[str, Any]:
        """Create a new API key for programmatic workspace access.

        The raw key is returned ONCE — it cannot be retrieved later.

        Args:
            workspace_id: Target workspace.
            data: Must contain 'name' and optionally 'scope' (read|submit|admin).
            db_session: RLS-scoped session injected by Litestar.

        Returns:
            API key details including the raw key (shown once).
        """
        name = data.get("name", "").strip()
        scope = data.get("scope", "submit")

        if not name:
            return {"error": "API key name is required"}

        if scope not in ("read", "submit", "admin"):
            return {"error": "Scope must be one of: read, submit, admin"}

        raw_key, hashed_key = _generate_api_key()

        api_key = ApiKey(
            workspace_id=workspace_id,
            name=name,
            key_hash=hashed_key,
            key_prefix=raw_key[:12],  # Store prefix for identification
            scope=scope,
            created_at=datetime.now(UTC),
        )
        db_session.add(api_key)
        await db_session.commit()

        logger.info(
            "api_key_created",
            workspace_id=str(workspace_id),
            name=name,
            scope=scope,
        )

        return {
            "id": str(api_key.id),
            "name": name,
            "scope": scope,
            "key": raw_key,  # Shown ONCE — user must save it
            "key_prefix": raw_key[:12],
            "created_at": api_key.created_at.isoformat(),
            "warning": "Save this key now — it cannot be retrieved later.",
        }

    @get("/")
    async def list_api_keys(
        self,
        workspace_id: UUID,
        db_session: AsyncSession,
    ) -> dict[str, Any]:
        """List all API keys for a workspace (without raw keys).

        Args:
            workspace_id: Target workspace.
            db_session: RLS-scoped session injected by Litestar.

        Returns:
            List of API keys with prefix, scope, and creation date.
        """
        result = await db_session.execute(
            select(ApiKey).where(
                ApiKey.workspace_id == workspace_id,
                ApiKey.is_active.is_(True),
            )
        )
        keys = result.scalars().all()

        return {
            "workspace_id": str(workspace_id),
            "keys": [
                {
                    "id": str(k.id),
                    "name": k.name,
                    "scope": k.scope,
                    "key_prefix": k.key_prefix,
                    "created_at": k.created_at.isoformat() if k.created_at else None,
                    "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                }
                for k in keys
            ],
        }

    @delete("/{key_id:uuid}")
    async def revoke_api_key(
        self,
        workspace_id: UUID,
        key_id: UUID,
        db_session: AsyncSession,
    ) -> dict[str, Any]:
        """Revoke an API key (soft delete).

        Args:
            workspace_id: Target workspace.
            key_id: API key to revoke.
            db_session: RLS-scoped session injected by Litestar.

        Returns:
            Confirmation of revocation.
        """
        key = await db_session.get(ApiKey, key_id)
        if not key or str(key.workspace_id) != str(workspace_id):
            return {"error": "API key not found"}

        key.is_active = False
        await db_session.commit()

        logger.info(
            "api_key_revoked",
            workspace_id=str(workspace_id),
            key_id=str(key_id),
            name=key.name,
        )

        return {"status": "revoked", "key_id": str(key_id)}
