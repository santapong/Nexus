"""Semantic memory writer + similarity recall.

Semantic memories are durable agent-level facts keyed by
``(agent_id, namespace, key)``. Unlike episodic rows (one per task), a
semantic row is an *upsert* — a fact that may be reasserted, corrected, or
contradicted over time.

This module owns:

* ``upsert_fact`` — contradiction-aware writer that scrubs secrets, decays
  confidence on conflicting writes (CLAUDE.md §25 "Semantic memory
  contradiction handling" — newest write does NOT automatically win), and
  dispatches embedding generation as a Taskiq fire-and-forget job.
* ``get_facts`` — namespace listing.
* ``recall_similar_facts`` — pgvector ``<=>`` recall with the same
  index-friendly ORDER BY pattern, configurable limit cap and similarity
  threshold as ``episodic.recall_similar``.
"""

from __future__ import annotations

from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import SemanticMemory
from nexus.memory.embeddings import redact_secrets, schedule_semantic_embedding
from nexus.memory.episodic import _cosine_distance  # reuse local cosine helper
from nexus.settings import settings

logger = structlog.get_logger()


async def upsert_fact(
    *,
    session: AsyncSession,
    agent_id: str,
    namespace: str,
    key: str,
    value: str,
    confidence: float = 1.0,
    source_task_id: str | None = None,
    trace_id: str = "",
) -> SemanticMemory:
    """Upsert a semantic memory fact (agent knowledge).

    Uses the unique constraint on (agent_id, namespace, key) for upsert.

    Contradiction handling (CLAUDE.md §25, resolved 2026-03):
    When an existing row's ``value`` differs from the incoming ``value``:
      * If the incoming ``confidence`` is **strictly higher** than the
        stored one, accept the new value at the new confidence.
      * Otherwise keep the existing value but **decrement** its confidence
        by ``settings.memory_contradiction_confidence_step`` (default 0.1),
        floored at ``settings.memory_contradiction_confidence_floor``
        (default 0.1). Repeated contradictions thus erode trust in the
        fact until a high-confidence writer overrides it.
    When values match, ``confidence`` is updated to ``max(existing, new)``
    so an agreeing higher-confidence write reinforces (rather than weakens)
    the fact.

    Secret redaction (CLAUDE.md §20 NEVER rule 4): ``value`` is scrubbed
    of API-key, JWT, and high-entropy patterns before the write. A
    redaction emits a WARNING but does not block.
    """
    safe_value, redacted = redact_secrets(value)
    if redacted:
        logger.warning(
            "memory_secret_redacted",
            table="semantic_memory",
            field="value",
            agent_id=agent_id,
            namespace=namespace,
            key=key,
            task_id=source_task_id or "",
        )

    stmt = select(SemanticMemory).where(
        SemanticMemory.agent_id == agent_id,
        SemanticMemory.namespace == namespace,
        SemanticMemory.key == key,
    )
    result = await session.execute(stmt)
    existing: SemanticMemory | None = result.scalar_one_or_none()

    if existing:
        contradicts = existing.value != safe_value
        accepted = False
        if not contradicts:
            # Reinforcement: same fact reasserted. Take max confidence so
            # repeated agreement strengthens (but never weakens) the row.
            existing.confidence = max(existing.confidence, confidence)
        elif confidence > existing.confidence:
            # Higher-confidence override wins outright.
            existing.value = safe_value
            existing.confidence = confidence
            accepted = True
        else:
            # Same-or-lower confidence + contradicting value → decay the
            # existing row's trust. Floor at the configured minimum so a
            # repeatedly-contradicted fact doesn't drop to zero and silently
            # disappear from confidence-filtered recall.
            existing.confidence = max(
                settings.memory_contradiction_confidence_floor,
                existing.confidence - settings.memory_contradiction_confidence_step,
            )
            logger.info(
                "semantic_contradiction_ignored",
                agent_id=agent_id,
                namespace=namespace,
                key=key,
                existing_confidence=existing.confidence,
                incoming_confidence=confidence,
                task_id=source_task_id or "",
            )

        if source_task_id:
            existing.source_task_id = source_task_id
        await session.flush()

        # Re-embed only when the stored value actually changed.
        if accepted:
            await schedule_semantic_embedding(
                fact_id=str(existing.id),
                text=safe_value,
                task_id=source_task_id or "",
                trace_id=trace_id,
            )
        return existing

    fact = SemanticMemory(
        id=uuid4(),
        agent_id=agent_id,
        namespace=namespace,
        key=key,
        value=safe_value,
        confidence=confidence,
        source_task_id=source_task_id,
    )
    session.add(fact)
    await session.flush()

    await schedule_semantic_embedding(
        fact_id=str(fact.id),
        text=safe_value,
        task_id=source_task_id or "",
        trace_id=trace_id,
    )

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
    limit: int | None = None,
    similarity_threshold: float | None = None,
) -> list[SemanticMemory]:
    """Recall semantic facts similar to a query embedding.

    Same index-friendly pattern as ``episodic.recall_similar``:
      * ``ORDER BY embedding <=> :query`` uses the ivfflat cosine index.
      * ``limit`` is bounded by ``settings.memory_recall_limit_max``.
      * Results below ``similarity_threshold`` are dropped.
    """
    effective_limit = settings.memory_recall_limit_default if limit is None else limit
    effective_limit = max(1, min(effective_limit, settings.memory_recall_limit_max))

    threshold = (
        settings.memory_recall_similarity_threshold
        if similarity_threshold is None
        else similarity_threshold
    )

    distance_expr = SemanticMemory.embedding.cosine_distance(query_embedding)
    stmt = (
        select(SemanticMemory)
        .where(SemanticMemory.agent_id == agent_id)
        .where(SemanticMemory.embedding.isnot(None))
        .order_by(distance_expr)
        .limit(effective_limit)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    max_distance = 1.0 - threshold
    filtered: list[SemanticMemory] = []
    for row in rows:
        emb = row.embedding
        if emb is None:
            continue
        try:
            distance = _cosine_distance(query_embedding, list(emb))
        except (TypeError, ValueError):
            continue
        if distance <= max_distance:
            filtered.append(row)

    return filtered
