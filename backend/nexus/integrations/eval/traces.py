"""Trace export — hooks LangFuse into the agent lifecycle.

Provides integration functions called by AgentBase and the eval runner
to automatically send traces to LangFuse without changing agent logic.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from nexus.integrations.eval.langfuse_client import (
    trace_eval_score,
    trace_llm_call,
    trace_task_execution,
)

logger = structlog.get_logger()


async def on_llm_call_completed(
    *,
    task_id: str,
    trace_id: str,
    agent_role: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    input_text: str = "",
    output_text: str = "",
    duration_ms: int = 0,
) -> None:
    """Hook called after every LLM call completes.

    Sends the call data to LangFuse for tracking.
    This function is non-blocking and never raises.

    Args:
        task_id: Task that triggered this call.
        trace_id: Trace group identifier.
        agent_role: Agent role making the call.
        model_name: LLM model used.
        input_tokens: Input token count.
        output_tokens: Output token count.
        cost_usd: Computed cost.
        input_text: Prompt text (optional, truncated).
        output_text: Response text (optional, truncated).
        duration_ms: Call duration in milliseconds.
    """
    try:
        await trace_llm_call(
            task_id=task_id,
            trace_id=trace_id,
            agent_role=agent_role,
            model_name=model_name,
            input_text=input_text,
            output_text=output_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
        )
    except Exception as exc:
        logger.debug("langfuse_hook_llm_failed", error=str(exc))


async def on_task_completed(
    *,
    task_id: str,
    trace_id: str,
    instruction: str,
    status: str,
    agent_role: str,
    tokens_used: int,
    duration_seconds: int,
    output: Any = None,
) -> None:
    """Hook called when a task finishes execution.

    Sends the task summary to LangFuse.
    This function is non-blocking and never raises.

    Args:
        task_id: Unique task identifier.
        trace_id: Trace group identifier.
        instruction: The original instruction.
        status: Final status (completed, failed).
        agent_role: Primary agent role.
        tokens_used: Total tokens consumed.
        duration_seconds: Total execution time.
        output: Task output (will be serialized and truncated).
    """
    try:
        output_preview = ""
        if output is not None:
            if isinstance(output, dict):
                output_preview = json.dumps(output)[:2000]
            else:
                output_preview = str(output)[:2000]

        await trace_task_execution(
            task_id=task_id,
            trace_id=trace_id,
            instruction=instruction,
            status=status,
            agent_role=agent_role,
            tokens_used=tokens_used,
            duration_seconds=duration_seconds,
            output_preview=output_preview,
        )
    except Exception as exc:
        logger.debug("langfuse_hook_task_failed", error=str(exc))


async def on_eval_scored(
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
    """Hook called after eval scoring completes for a task.

    Sends dimension scores to LangFuse.
    This function is non-blocking and never raises.

    Args:
        task_id: The evaluated task.
        trace_id: Trace group identifier.
        overall_score: Aggregate score.
        relevance: Relevance score.
        completeness: Completeness score.
        accuracy: Accuracy score.
        formatting: Formatting score.
        judge_reasoning: Judge explanation.
        judge_model: Model used for judging.
    """
    try:
        await trace_eval_score(
            task_id=task_id,
            trace_id=trace_id,
            overall_score=overall_score,
            relevance=relevance,
            completeness=completeness,
            accuracy=accuracy,
            formatting=formatting,
            judge_reasoning=judge_reasoning,
            judge_model=judge_model,
        )
    except Exception as exc:
        logger.debug("langfuse_hook_eval_failed", error=str(exc))
