"""Workspace API key management — programmatic access.

Allows workspace owners to create API keys for programmatic task submission.
Keys are scoped by permission level: read-only, task-submit, or admin.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from litestar import Controller, delete, get, post

from nexus.db.models import ApiKey
from nexus.db.session import sqlalchemy_config

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
    ) -> dict[str, Any]:
        """Create a new API key for programmatic workspace access.

        The raw key is returned ONCE — it cannot be retrieved later.

        Args:
            workspace_id: Target workspace.
            data: Must contain 'name' and optionally 'scope' (read|submit|admin).

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

        async with sqlalchemy_config.get_session() as session:
            api_key = ApiKey(
                workspace_id=workspace_id,
                name=name,
                key_hash=hashed_key,
                key_prefix=raw_key[:12],  # Store prefix for identification
                scope=scope,
                created_at=datetime.now(UTC),
            )
            session.add(api_key)
            await session.commit()

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
    ) -> dict[str, Any]:
        """List all API keys for a workspace (without raw keys).

        Args:
            workspace_id: Target workspace.

        Returns:
            List of API keys with prefix, scope, and creation date.
        """
        from sqlalchemy import select

        async with sqlalchemy_config.get_session() as session:
            result = await session.execute(
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
    ) -> dict[str, Any]:
        """Revoke an API key (soft delete).

        Args:
            workspace_id: Target workspace.
            key_id: API key to revoke.

        Returns:
            Confirmation of revocation.
        """
        async with sqlalchemy_config.get_session() as session:
            key = await session.get(ApiKey, key_id)
            if not key or str(key.workspace_id) != str(workspace_id):
                return {"error": "API key not found"}

            key.is_active = False
            await session.commit()

            logger.info(
                "api_key_revoked",
                workspace_id=str(workspace_id),
                key_id=str(key_id),
                name=key.name,
            )

            return {"status": "revoked", "key_id": str(key_id)}
