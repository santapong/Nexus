from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import EpisodicMemory


async def write_episode(
    *,
    session: AsyncSession,
    agent_id: str,
    task_id: str,
    summary: str,
    full_context: dict[str, Any],
    outcome: str,
    tools_used: list[str] | None = None,
    tokens_used: int | None = None,
    duration_seconds: int | None = None,
    importance_score: float = 0.5,
) -> EpisodicMemory:
    """Write an episodic memory record after task completion.

    Must be called BEFORE publishing task result to Kafka.
    """
    episode = EpisodicMemory(
        id=uuid4(),
        agent_id=agent_id,
        task_id=task_id,
        summary=summary,
        full_context=full_context,
        outcome=outcome,
        tools_used=tools_used,
        tokens_used=tokens_used,
        duration_seconds=duration_seconds,
        importance_score=importance_score,
    )
    session.add(episode)
    await session.flush()
    return episode


async def recall_similar(
    *,
    session: AsyncSession,
    agent_id: str,
    query_embedding: list[float],
    limit: int = 5,
) -> list[EpisodicMemory]:
    """Recall episodic memories similar to a query embedding.

    Uses pgvector cosine distance for similarity search.
    """
    stmt = (
        select(EpisodicMemory)
        .where(EpisodicMemory.agent_id == agent_id)
        .where(EpisodicMemory.embedding.isnot(None))
        .order_by(EpisodicMemory.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
