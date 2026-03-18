"""LangFuse integration — external eval tracking and observability.

Sends LLM call traces, eval scores, and task execution data to LangFuse
for centralized observability. Falls back gracefully when LangFuse is
not configured (empty host/keys).

LangFuse replaces manual eval logging with a full observability platform
for tracking prompt quality, model costs, and agent performance over time.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.settings import settings

logger = structlog.get_logger()

# Module-level client — initialized lazily on first use
_langfuse_client: Any | None = None
_langfuse_available: bool | None = None


def _get_langfuse_client() -> Any | None:
    """Get or create the LangFuse client singleton.

    Returns None if LangFuse is not configured or not installed.

    Returns:
        LangFuse client instance, or None if unavailable.
    """
    global _langfuse_client, _langfuse_available

    if _langfuse_available is False:
        return None

    if _langfuse_client is not None:
        return _langfuse_client

    if not settings.langfuse_host or not settings.langfuse_public_key:
        logger.debug(
            "langfuse_not_configured",
            message="Set LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY to enable.",
        )
        _langfuse_available = False
        return None

    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            host=settings.langfuse_host,
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
        )
        _langfuse_available = True
        logger.info(
            "langfuse_client_initialized",
            host=settings.langfuse_host,
        )
        return _langfuse_client

    except ImportError:
        logger.warning(
            "langfuse_not_installed",
            message="Install with: pip install langfuse",
        )
        _langfuse_available = False
        return None
    except Exception as exc:
        logger.error(
            "langfuse_init_failed",
            error=str(exc),
        )
        _langfuse_available = False
        return None


async def trace_llm_call(
    *,
    task_id: str,
    trace_id: str,
    agent_role: str,
    model_name: str,
    input_text: str,
    output_text: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    duration_ms: int = 0,
) -> None:
    """Send an LLM call trace to LangFuse.

    Args:
        task_id: The task that triggered this LLM call.
        trace_id: Trace group identifier.
        agent_role: Which agent made the call (ceo, engineer, etc.).
        model_name: LLM model used.
        input_text: Prompt sent to the model (truncated for storage).
        output_text: Model response (truncated for storage).
        input_tokens: Input token count.
        output_tokens: Output token count.
        cost_usd: Computed cost in USD.
        duration_ms: Call duration in milliseconds.
    """
    client = _get_langfuse_client()
    if client is None:
        return

    try:
        trace = client.trace(
            id=trace_id,
            name=f"task-{task_id}",
            metadata={
                "task_id": task_id,
                "agent_role": agent_role,
            },
        )

        trace.generation(
            name=f"{agent_role}-llm-call",
            model=model_name,
            input=input_text[:5000],
            output=output_text[:5000],
            usage={
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
            },
            metadata={
                "cost_usd": cost_usd,
                "duration_ms": duration_ms,
                "agent_role": agent_role,
            },
        )

        logger.debug(
            "langfuse_trace_sent",
            task_id=task_id,
            agent_role=agent_role,
            model=model_name,
        )

    except Exception as exc:
        # LangFuse failures are non-critical — log and continue
        logger.warning(
            "langfuse_trace_failed",
            task_id=task_id,
            error=str(exc),
        )


async def trace_eval_score(
    *,
    task_id: str,
    trace_id: str,
    overall_score: float,
    relevance: float,
    completeness: float,
    accuracy: float,
    formatting: float,
    judge_reasoning: str,
    judge_model: str,
) -> None:
    """Send eval scores to LangFuse as a score event.

    Args:
        task_id: The evaluated task.
        trace_id: Trace group identifier.
        overall_score: Aggregate quality score (0-1).
        relevance: Relevance dimension score.
        completeness: Completeness dimension score.
        accuracy: Accuracy dimension score.
        formatting: Formatting dimension score.
        judge_reasoning: LLM judge explanation.
        judge_model: Model used for judging.
    """
    client = _get_langfuse_client()
    if client is None:
        return

    try:
        trace = client.trace(
            id=trace_id,
            name=f"eval-{task_id}",
        )

        trace.score(
            name="overall_quality",
            value=overall_score,
            comment=judge_reasoning[:1000],
        )
        trace.score(name="relevance", value=relevance)
        trace.score(name="completeness", value=completeness)
        trace.score(name="accuracy", value=accuracy)
        trace.score(name="formatting", value=formatting)

        logger.debug(
            "langfuse_eval_sent",
            task_id=task_id,
            overall_score=overall_score,
            judge_model=judge_model,
        )

    except Exception as exc:
        logger.warning(
            "langfuse_eval_trace_failed",
            task_id=task_id,
            error=str(exc),
        )


async def trace_task_execution(
    *,
    task_id: str,
    trace_id: str,
    instruction: str,
    status: str,
    agent_role: str,
    tokens_used: int,
    duration_seconds: int,
    output_preview: str = "",
) -> None:
    """Send a task execution trace to LangFuse.

    Args:
        task_id: Unique task identifier.
        trace_id: Trace group identifier.
        instruction: The task instruction.
        status: Final task status (completed, failed, etc.).
        agent_role: Primary agent that handled the task.
        tokens_used: Total tokens consumed.
        duration_seconds: Total execution time.
        output_preview: Truncated output for context.
    """
    client = _get_langfuse_client()
    if client is None:
        return

    try:
        client.trace(
            id=trace_id,
            name=f"task-{task_id}",
            input=instruction[:2000],
            output=output_preview[:2000],
            metadata={
                "task_id": task_id,
                "status": status,
                "agent_role": agent_role,
                "tokens_used": tokens_used,
                "duration_seconds": duration_seconds,
            },
        )

        logger.debug(
            "langfuse_task_trace_sent",
            task_id=task_id,
            status=status,
        )

    except Exception as exc:
        logger.warning(
            "langfuse_task_trace_failed",
            task_id=task_id,
            error=str(exc),
        )


def flush_langfuse() -> None:
    """Flush any pending LangFuse events.

    Call this on application shutdown to ensure all traces are sent.
    """
    client = _get_langfuse_client()
    if client is not None:
        try:
            client.flush()
            logger.info("langfuse_flushed")
        except Exception as exc:
            logger.warning("langfuse_flush_failed", error=str(exc))
