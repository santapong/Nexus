"""Federation registry — multi-NEXUS instance discovery.

Manages a centralized registry of known NEXUS instances. Each instance
registers its Agent Card, which is periodically refreshed. Agents can
query the registry to discover external instances with specific capabilities.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import FederationInstance

logger = structlog.get_logger()


async def register_instance(
    instance_url: str,
    *,
    db_session: AsyncSession,
    trust_level: str = "untrusted",
) -> FederationInstance | None:
    """Register a remote NEXUS instance by fetching its Agent Card.

    Args:
        instance_url: Base URL of the remote instance (e.g. https://nexus.example.com).
        db_session: Async database session.
        trust_level: Initial trust level (untrusted|verified|trusted).

    Returns:
        The created or updated FederationInstance, or None on fetch failure.
    """
    url = instance_url.rstrip("/")
    agent_card_url = f"{url}/.well-known/agent.json"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(agent_card_url, timeout=15.0)
            response.raise_for_status()
            card_data = response.json()
    except Exception as exc:
        logger.error(
            "federation_fetch_failed",
            instance_url=url,
            error=str(exc),
        )
        return None

    instance_name = card_data.get("name", "Unknown NEXUS Instance")
    capabilities = [s.get("id", "") for s in card_data.get("skills", []) if s.get("id")]

    # Upsert — update if exists, create if not
    stmt = select(FederationInstance).where(FederationInstance.instance_url == url)
    result = await db_session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.agent_card = card_data
        existing.instance_name = instance_name
        existing.capabilities = capabilities
        existing.last_seen_at = datetime.now(UTC)
        existing.is_active = True
        await db_session.commit()
        logger.info(
            "federation_instance_updated",
            instance_url=url,
            name=instance_name,
        )
        return existing

    instance = FederationInstance(
        instance_url=url,
        instance_name=instance_name,
        agent_card=card_data,
        trust_level=trust_level,
        capabilities=capabilities,
        last_seen_at=datetime.now(UTC),
    )
    db_session.add(instance)
    await db_session.commit()
    await db_session.refresh(instance)

    logger.info(
        "federation_instance_registered",
        instance_url=url,
        name=instance_name,
        capabilities=capabilities,
    )
    return instance


async def discover_instances(
    *,
    skill_id: str | None = None,
    trust_level: str | None = None,
    db_session: AsyncSession,
) -> list[FederationInstance]:
    """Query the federation registry for active instances.

    Args:
        skill_id: Filter by capability/skill ID.
        trust_level: Filter by minimum trust level.
        db_session: Async database session.

    Returns:
        List of matching FederationInstance records.
    """
    stmt = select(FederationInstance).where(FederationInstance.is_active.is_(True))

    if trust_level:
        stmt = stmt.where(FederationInstance.trust_level == trust_level)

    if skill_id:
        stmt = stmt.where(FederationInstance.capabilities.any(skill_id))

    stmt = stmt.order_by(FederationInstance.registered_at.desc())
    result = await db_session.execute(stmt)
    return list(result.scalars().all())


async def refresh_registry(*, db_session: AsyncSession) -> dict[str, int]:
    """Refresh all active federation entries by re-fetching Agent Cards.

    Args:
        db_session: Async database session.

    Returns:
        Dict with counts: refreshed, failed, deactivated.
    """
    stmt = select(FederationInstance).where(FederationInstance.is_active.is_(True))
    result = await db_session.execute(stmt)
    instances = result.scalars().all()

    refreshed = 0
    failed = 0

    for instance in instances:
        updated = await register_instance(
            instance.instance_url,
            db_session=db_session,
            trust_level=instance.trust_level,
        )
        if updated:
            refreshed += 1
        else:
            failed += 1

    logger.info(
        "federation_registry_refreshed",
        total=len(instances),
        refreshed=refreshed,
        failed=failed,
    )
    return {"refreshed": refreshed, "failed": failed, "total": len(instances)}


async def deactivate_instance(
    instance_id: str,
    *,
    db_session: AsyncSession,
) -> bool:
    """Deactivate a federation registry entry.

    Args:
        instance_id: UUID of the federation instance.
        db_session: Async database session.

    Returns:
        True if found and deactivated, False otherwise.
    """
    stmt = (
        update(FederationInstance)
        .where(FederationInstance.id == instance_id)
        .values(is_active=False)
    )
    result = await db_session.execute(stmt)
    await db_session.commit()

    if result.rowcount > 0:
        logger.info("federation_instance_deactivated", instance_id=instance_id)
        return True
    return False
