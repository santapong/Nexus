"""Embedding generation + secret redaction helpers for the memory module.

Two responsibilities, both colocated here because every memory writer needs
them on the hot path:

1. ``generate_embedding`` — direct (awaitable) call to Google embedding-001.
   Used during recall, where the caller needs the vector synchronously.
2. ``schedule_episode_embedding`` / ``schedule_semantic_embedding`` —
   Taskiq fire-and-forget tasks that populate ``embedding`` columns on
   already-persisted rows. Per CLAUDE.md §12 ("Generate async via Taskiq
   fire-and-forget task on every episodic/semantic write — never block
   task completion waiting for embedding"), episodic/semantic writes MUST
   NOT block on embedding generation.
3. ``redact_secrets`` — regex-based scrubber for the three secret families
   listed in CLAUDE.md §20 NEVER rule 4. Used by ``episodic.write_episode``
   and ``semantic.upsert_fact`` to prevent secrets from ever landing in
   memory tables.
"""

from __future__ import annotations

import re
from uuid import UUID

import httpx
import structlog
from sqlalchemy import update

from nexus.settings import settings
from nexus.taskiq_app import broker

logger = structlog.get_logger()

# Google embedding-001 dimension
EMBEDDING_DIMENSION = 1536


# ─── Secret redaction ────────────────────────────────────────────────────────
#
# CLAUDE.md §20 NEVER rule 4: "Never store secrets in memory tables. API keys,
# passwords, tokens must never appear in episodic_memory or semantic_memory."
#
# These patterns are deliberately narrow: they target high-confidence secret
# shapes (labelled API-key-style assignments, JWT tokens, long high-entropy
# hex/base64 strings). False positives are acceptable — we'd rather scrub a
# legitimate-looking hash than persist a real bearer token.

_REDACTED = "[REDACTED]"

# Labelled secret assignments: api_key, api-key, secret, token, password, bearer,
# aws_access_key, aws_secret_key. Followed by 16+ chars of base64/hex-ish payload.
_LABELLED_SECRET = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|bearer|aws_(?:access|secret)_key)"
    r"[\s:=]+[\"']?[A-Za-z0-9+/=_\-]{16,}"
)

# JWT-shaped tokens (header.payload.signature, header and payload starting eyJ).
_JWT_TOKEN = re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")

# Generic high-entropy hex/base64 strings of length ≥ 32 (catches stray API
# keys that aren't labelled). Word boundaries prevent over-greedy matches
# inside larger tokens already redacted above.
_HIGH_ENTROPY_HEX_OR_B64 = re.compile(r"\b[A-Za-z0-9+/=_\-]{32,}\b")

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    _LABELLED_SECRET,
    _JWT_TOKEN,
    _HIGH_ENTROPY_HEX_OR_B64,
)


def redact_secrets(text: str) -> tuple[str, bool]:
    """Strip secret-shaped substrings from ``text`` and return the scrubbed copy.

    Order matters: labelled assignments and JWTs run first so the
    high-entropy catch-all does not partially clobber them.

    Args:
        text: Raw value about to be written to a memory table.

    Returns:
        ``(scrubbed_text, was_redacted)``. ``was_redacted`` is True if any
        pattern matched, allowing the caller to log a WARNING (per spec —
        log but DO NOT block the write).
    """
    if not text:
        return text, False

    scrubbed = text
    redacted = False
    for pattern in _SECRET_PATTERNS:
        new = pattern.sub(_REDACTED, scrubbed)
        if new != scrubbed:
            redacted = True
            scrubbed = new
    return scrubbed, redacted


# ─── Synchronous embedding generation ───────────────────────────────────────


async def generate_embedding(text: str) -> list[float] | None:
    """Generate an embedding using Google embedding-001 via Gemini API.

    Returns None on failure (embedding is non-blocking).
    """
    if not settings.google_api_key:
        logger.warning("embedding_skipped", reason="no_google_api_key")
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://generativelanguage.googleapis.com/v1/models/embedding-001:embedContent",
                params={"key": settings.google_api_key},
                json={
                    "model": "models/embedding-001",
                    "content": {"parts": [{"text": text}]},
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["embedding"]["values"]  # type: ignore[no-any-return]
    except Exception as exc:
        logger.error("embedding_generation_failed", error=str(exc))
        return None


# ─── Taskiq fire-and-forget embedding writers ───────────────────────────────
#
# CLAUDE.md §12: "Generate async via Taskiq fire-and-forget task on every
# episodic/semantic write. Never block task completion waiting for embedding."
#
# Writers call ``schedule_*_embedding`` (a sync .kiq() dispatch) after the
# row is flushed. The task then loads the row, generates the embedding, and
# writes the vector back. Failure is non-fatal — the row simply remains
# without an embedding and is excluded from similarity recall.


def _coerce_uuid(value: str | UUID) -> str:
    return str(value)


@broker.task(retry_on_error=True, max_retries=3, timeout=120)
async def generate_embedding_for_episode(
    episode_id: str,
    text: str,
    task_id: str = "",
    trace_id: str = "",
) -> bool:
    """Generate and persist the embedding for one ``episodic_memory`` row.

    Fire-and-forget — the parent task is already complete by the time this
    runs. Idempotent: re-running overwrites the embedding with the same
    vector (Google embedding-001 is deterministic enough for this purpose).

    Args:
        episode_id: PK of the ``episodic_memory`` row.
        text: Source text (usually the summary) to embed.
        task_id: Originating task_id for log correlation.
        trace_id: Originating trace_id for log correlation.

    Returns:
        True if the embedding was written, False on any failure.
    """
    from nexus.db.models import EpisodicMemory
    from nexus.db.session import get_session_factory

    embedding = await generate_embedding(text)
    if embedding is None:
        logger.warning(
            "episode_embedding_skipped",
            episode_id=episode_id,
            task_id=task_id,
            trace_id=trace_id,
        )
        return False

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            await session.execute(
                update(EpisodicMemory)
                .where(EpisodicMemory.id == episode_id)
                .values(embedding=embedding)
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.error(
                "episode_embedding_write_failed",
                episode_id=episode_id,
                task_id=task_id,
                error=str(exc),
            )
            return False

    logger.info(
        "episode_embedding_written",
        episode_id=episode_id,
        task_id=task_id,
        trace_id=trace_id,
    )
    return True


@broker.task(retry_on_error=True, max_retries=3, timeout=120)
async def generate_embedding_for_semantic_fact(
    fact_id: str,
    text: str,
    task_id: str = "",
    trace_id: str = "",
) -> bool:
    """Generate and persist the embedding for one ``semantic_memory`` row.

    Mirrors ``generate_embedding_for_episode``. See that docstring for
    semantics — this version targets the ``semantic_memory`` table.
    """
    from nexus.db.models import SemanticMemory
    from nexus.db.session import get_session_factory

    embedding = await generate_embedding(text)
    if embedding is None:
        logger.warning(
            "semantic_embedding_skipped",
            fact_id=fact_id,
            task_id=task_id,
            trace_id=trace_id,
        )
        return False

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            await session.execute(
                update(SemanticMemory)
                .where(SemanticMemory.id == fact_id)
                .values(embedding=embedding)
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.error(
                "semantic_embedding_write_failed",
                fact_id=fact_id,
                task_id=task_id,
                error=str(exc),
            )
            return False

    logger.info(
        "semantic_embedding_written",
        fact_id=fact_id,
        task_id=task_id,
        trace_id=trace_id,
    )
    return True


async def schedule_episode_embedding(
    *,
    episode_id: str | UUID,
    text: str,
    task_id: str = "",
    trace_id: str = "",
) -> None:
    """Dispatch the embedding generation for an episode without blocking.

    The episode row MUST already be flushed/committed by the time this is
    called — the Taskiq worker will look it up by ``episode_id``.

    Errors here are swallowed: if Kafka/Taskiq is down we still want the
    task result to be published. The row remains without an embedding and
    will simply be excluded from similarity recall until it is backfilled.
    """
    try:
        await generate_embedding_for_episode.kiq(
            _coerce_uuid(episode_id),
            text,
            task_id=task_id,
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.warning(
            "episode_embedding_dispatch_failed",
            episode_id=str(episode_id),
            task_id=task_id,
            error=str(exc),
        )


async def schedule_semantic_embedding(
    *,
    fact_id: str | UUID,
    text: str,
    task_id: str = "",
    trace_id: str = "",
) -> None:
    """Dispatch the embedding generation for a semantic fact without blocking.

    Mirror of ``schedule_episode_embedding``.
    """
    try:
        await generate_embedding_for_semantic_fact.kiq(
            _coerce_uuid(fact_id),
            text,
            task_id=task_id,
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.warning(
            "semantic_embedding_dispatch_failed",
            fact_id=str(fact_id),
            task_id=task_id,
            error=str(exc),
        )
