"""Episodic memory writer + similarity recall.

Episodic memories are per-task records — what happened, what tools fired,
what the outcome was — embedded for semantic recall on future tasks. This
module owns the canonical write path (with secret redaction + async
embedding dispatch) and the canonical recall query (using the pgvector
ivfflat index on ``embedding vector_cosine_ops``).

CLAUDE.md references:
* §12 schema + embedding strategy (Taskiq fire-and-forget).
* §20 NEVER rule 4 — no secrets in memory tables.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import EpisodicMemory
from nexus.memory.embeddings import redact_secrets, schedule_episode_embedding
from nexus.settings import settings

logger = structlog.get_logger()


def _scrub_value(
    value: Any,
    *,
    agent_id: str,
    task_id: str,
    field: str,
) -> Any:
    """Recursively redact secret-shaped substrings from a JSON-able value.

    Strings are passed through ``redact_secrets``. Containers (dict/list) are
    walked. Non-string leaves (int, bool, None, float) are returned as-is.
    A WARNING is logged per redacted leaf, but the write is never blocked.
    """
    if isinstance(value, str):
        scrubbed, redacted = redact_secrets(value)
        if redacted:
            logger.warning(
                "memory_secret_redacted",
                table="episodic_memory",
                field=field,
                agent_id=agent_id,
                task_id=task_id,
            )
        return scrubbed
    if isinstance(value, dict):
        return {
            k: _scrub_value(v, agent_id=agent_id, task_id=task_id, field=f"{field}.{k}")
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            _scrub_value(v, agent_id=agent_id, task_id=task_id, field=f"{field}[{i}]")
            for i, v in enumerate(value)
        ]
    return value


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
    trace_id: str = "",
) -> EpisodicMemory:
    """Write an episodic memory record after task completion.

    Must be called BEFORE publishing task result to Kafka.

    Behaviour:
    * Scrubs ``summary`` and ``full_context`` of secret-shaped substrings
      (CLAUDE.md §20 NEVER rule 4). Redactions log a WARNING but do not
      block the write.
    * Dispatches a Taskiq fire-and-forget job to populate the ``embedding``
      column asynchronously (CLAUDE.md §12 — never block task completion
      on embedding generation).
    """
    safe_summary = _scrub_value(summary, agent_id=agent_id, task_id=task_id, field="summary")
    safe_context = _scrub_value(
        full_context, agent_id=agent_id, task_id=task_id, field="full_context"
    )

    episode = EpisodicMemory(
        id=uuid4(),
        agent_id=agent_id,
        task_id=task_id,
        summary=safe_summary,
        full_context=safe_context,
        outcome=outcome,
        tools_used=tools_used,
        tokens_used=tokens_used,
        duration_seconds=duration_seconds,
        importance_score=importance_score,
    )
    session.add(episode)
    await session.flush()

    # Fire-and-forget embedding dispatch. We embed a compact representation:
    # the summary plus a JSON-serialised view of the (already-scrubbed) full
    # context. This gives recall queries a richer signal than the summary
    # alone while staying small enough to fit one embedding call.
    try:
        embed_payload = safe_summary
        if isinstance(safe_context, dict) and safe_context:
            embed_payload = f"{safe_summary}\n\n{json.dumps(safe_context, default=str)[:4000]}"
    except Exception:
        embed_payload = safe_summary

    await schedule_episode_embedding(
        episode_id=str(episode.id),
        text=embed_payload,
        task_id=task_id,
        trace_id=trace_id,
    )

    return episode


async def recall_similar(
    *,
    session: AsyncSession,
    agent_id: str,
    query_embedding: list[float],
    limit: int | None = None,
    similarity_threshold: float | None = None,
) -> list[EpisodicMemory]:
    """Recall episodic memories similar to a query embedding.

    Uses pgvector cosine distance (``<=>``) for similarity search. The
    ``ORDER BY`` is on ``embedding <=> :query`` directly, which matches the
    ivfflat index on ``embedding vector_cosine_ops`` created by the migration
    that pairs with this query. Any other ordering — e.g. a calculated
    similarity score in the SELECT — would bypass the index and force a
    sequential scan.

    Limits:
    * ``limit`` defaults to ``settings.memory_recall_limit_default`` (5).
    * ``limit`` is hard-capped at ``settings.memory_recall_limit_max`` (20)
      so a runaway caller cannot scan an entire shard.
    * Results with cosine similarity below ``similarity_threshold``
      (default 0.7) are filtered out — recalling weakly-related episodes
      tends to confuse the LLM more than help it.
    """
    effective_limit = settings.memory_recall_limit_default if limit is None else limit
    effective_limit = max(1, min(effective_limit, settings.memory_recall_limit_max))

    threshold = (
        settings.memory_recall_similarity_threshold
        if similarity_threshold is None
        else similarity_threshold
    )

    # ORDER BY the indexed expression (embedding <=> :query). The index is
    # ivfflat(vector_cosine_ops); any expression that wraps the column
    # (e.g. 1 - distance) would defeat it.
    distance_expr = EpisodicMemory.embedding.cosine_distance(query_embedding)
    stmt = (
        select(EpisodicMemory)
        .where(EpisodicMemory.agent_id == agent_id)
        .where(EpisodicMemory.embedding.isnot(None))
        .order_by(distance_expr)
        .limit(effective_limit)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    # Post-filter by similarity. We re-compute similarity on the Python
    # side from the embedding column rather than push another DB round-trip;
    # this is fine because ``limit`` is capped at 20.
    max_distance = 1.0 - threshold
    filtered: list[EpisodicMemory] = []
    for row in rows:
        emb = row.embedding
        if emb is None:
            continue
        # Python fallback cosine distance (pgvector returns the raw column,
        # which sqlalchemy maps to a list[float]). We deliberately compute
        # locally to apply the threshold without an extra round-trip.
        try:
            distance = _cosine_distance(query_embedding, list(emb))
        except (TypeError, ValueError):
            continue
        if distance <= max_distance:
            filtered.append(row)

    return filtered


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Cosine distance (1 - cosine similarity) for two equal-length vectors.

    Returns ``1.0`` (max distance) for zero-norm vectors. Mirrors what the
    pgvector ``<=>`` operator computes, so post-filtering here is consistent
    with the ORDER BY clause's ranking.
    """
    if len(a) != len(b):
        raise ValueError("vector length mismatch")
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0
    similarity = dot / ((norm_a**0.5) * (norm_b**0.5))
    return 1.0 - similarity
