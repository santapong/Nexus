"""Federation registry API — multi-NEXUS instance discovery.

Endpoints:
- POST /api/federation/register  — Register a remote NEXUS instance
- GET  /api/federation/instances — List registered instances
- DELETE /api/federation/instances/{id} — Deactivate an instance
- POST /api/federation/refresh   — Refresh all Agent Cards
"""

from __future__ import annotations

from typing import Any

import structlog
from litestar import Controller, delete, get, post
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.integrations.a2a.federation import (
    deactivate_instance,
    discover_instances,
    refresh_registry,
    register_instance,
)

logger = structlog.get_logger()


class RegisterInstanceRequest(BaseModel):
    """Request to register a remote NEXUS instance."""

    instance_url: str
    trust_level: str = "untrusted"


class FederationInstanceResponse(BaseModel):
    """Federation instance details."""

    id: str
    instance_url: str
    instance_name: str
    trust_level: str
    capabilities: list[str]
    registered_at: str
    last_seen_at: str | None
    is_active: bool


class FederationController(Controller):
    """Federation registry management."""

    path = "/federation"

    @post("/register")
    async def register(
        self,
        data: RegisterInstanceRequest,
        db_session: AsyncSession,
    ) -> FederationInstanceResponse | dict[str, str]:
        """Register a remote NEXUS instance by URL.

        Fetches the instance's Agent Card from /.well-known/agent.json
        and stores it in the federation registry.

        Args:
            data: Registration request with instance URL.
            db_session: Async database session.

        Returns:
            FederationInstanceResponse on success, error dict on failure.
        """
        instance = await register_instance(
            data.instance_url,
            db_session=db_session,
            trust_level=data.trust_level,
        )

        if instance is None:
            return {"error": f"Failed to fetch Agent Card from {data.instance_url}"}

        return FederationInstanceResponse(
            id=str(instance.id),
            instance_url=instance.instance_url,
            instance_name=instance.instance_name,
            trust_level=instance.trust_level,
            capabilities=instance.capabilities,
            registered_at=str(instance.registered_at),
            last_seen_at=str(instance.last_seen_at) if instance.last_seen_at else None,
            is_active=instance.is_active,
        )

    @get("/instances")
    async def list_instances(
        self,
        db_session: AsyncSession,
        skill_id: str | None = None,
        trust_level: str | None = None,
    ) -> list[FederationInstanceResponse]:
        """List registered federation instances.

        Args:
            db_session: Async database session.
            skill_id: Filter by capability.
            trust_level: Filter by trust level.

        Returns:
            List of federation instances.
        """
        instances = await discover_instances(
            skill_id=skill_id,
            trust_level=trust_level,
            db_session=db_session,
        )

        return [
            FederationInstanceResponse(
                id=str(i.id),
                instance_url=i.instance_url,
                instance_name=i.instance_name,
                trust_level=i.trust_level,
                capabilities=i.capabilities,
                registered_at=str(i.registered_at),
                last_seen_at=str(i.last_seen_at) if i.last_seen_at else None,
                is_active=i.is_active,
            )
            for i in instances
        ]

    @delete("/instances/{instance_id:str}")
    async def remove_instance(
        self,
        instance_id: str,
        db_session: AsyncSession,
    ) -> dict[str, Any]:
        """Deactivate a federation instance.

        Args:
            instance_id: UUID of the instance to deactivate.
            db_session: Async database session.

        Returns:
            Success or error message.
        """
        removed = await deactivate_instance(instance_id, db_session=db_session)
        if not removed:
            return {"error": "Instance not found"}
        return {"status": "deactivated", "instance_id": instance_id}

    @post("/refresh")
    async def refresh(
        self,
        db_session: AsyncSession,
    ) -> dict[str, int]:
        """Refresh all active federation entries.

        Re-fetches Agent Cards from all registered instances.

        Args:
            db_session: Async database session.

        Returns:
            Counts of refreshed, failed, and total instances.
        """
        return await refresh_registry(db_session=db_session)
