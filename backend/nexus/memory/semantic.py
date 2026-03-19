from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import SemanticMemory


async def upsert_fact(
    *,
    session: AsyncSession,
    agent_id: str,
    namespace: str,
    key: str,
    value: str,
    confidence: float = 1.0,
    source_task_id: str | None = None,
) -> SemanticMemory:
    """Upsert a semantic memory fact (agent knowledge).

    Uses the unique constraint on (agent_id, namespace, key) for upsert.
    """
    stmt = select(SemanticMemory).where(
        SemanticMemory.agent_id == agent_id,
        SemanticMemory.namespace == namespace,
        SemanticMemory.key == key,
    )
    result = await session.execute(stmt)
    existing: SemanticMemory | None = result.scalar_one_or_none()

    if existing:
        existing.value = value
        existing.confidence = confidence
        if source_task_id:
            existing.source_task_id = source_task_id
        await session.flush()
        return existing

    fact = SemanticMemory(
        id=uuid4(),
        agent_id=agent_id,
        namespace=namespace,
        key=key,
        value=value,
        confidence=confidence,
        source_task_id=source_task_id,
    )
    session.add(fact)
    await session.flush()
    return fact


async def get_facts(
    *,
    session: AsyncSession,
    agent_id: str,
    namespace: str,
) -> list[SemanticMemory]:
    """Get all semantic memory facts for an agent in a namespace."""
    stmt = (
        select(SemanticMemory)
        .where(
            SemanticMemory.agent_id == agent_id,
            SemanticMemory.namespace == namespace,
        )
        .order_by(SemanticMemory.key)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def recall_similar_facts(
    *,
    session: AsyncSession,
    agent_id: str,
    query_embedding: list[float],
    limit: int = 5,
) -> list[SemanticMemory]:
    """Recall semantic facts similar to a query embedding."""
    stmt = (
        select(SemanticMemory)
        .where(SemanticMemory.agent_id == agent_id)
        .where(SemanticMemory.embedding.isnot(None))
        .order_by(SemanticMemory.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
