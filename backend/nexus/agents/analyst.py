"""Analyst Agent — research and data analysis specialist (Phase 2).

Handles research tasks, data analysis, competitive analysis,
and report generation using web search, web fetch, and file tools.
"""

from __future__ import annotations

import asyncio

import structlog
from pydantic_ai import Agent as PydanticAgent
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.agents.base import AgentBase
from nexus.core.kafka.schemas import AgentCommand, AgentResponse
from nexus.core.llm.usage import calculate_cost, record_usage

logger = structlog.get_logger()

_MAX_RETRIES = 5
_RETRY_BACKOFF_SECONDS = [5.0, 10.0, 20.0, 30.0, 45.0]


class AnalystAgent(AgentBase):
    """Analyst agent — executes research and data analysis tasks."""

    async def handle_task(self, message: AgentCommand, session: AsyncSession) -> AgentResponse:
        """Execute a research/analysis task using the Pydantic AI agent with tools."""
        task_id = str(message.task_id)
        trace_id = str(message.trace_id)

        logger.info(
            "analyst_task_started",
            task_id=task_id,
            trace_id=trace_id,
            instruction=message.instruction[:200],
        )

        # Build prompt context from loaded memory
        memory_context = getattr(self, "_memory_context", {})
        context_parts: list[str] = []

        if memory_context.get("similar_episodes"):
            context_parts.append(
                "Relevant past research:\n"
                + "\n".join(f"- {ep}" for ep in memory_context["similar_episodes"])
            )

        if memory_context.get("working_memory"):
            context_parts.append("Working memory:\n" + str(memory_context["working_memory"]))

        if context_parts:
            user_message = "\n\n".join(context_parts) + f"\n\nTask: {message.instruction}"
        else:
            user_message = message.instruction

        result = await self._run_with_retry(user_message, task_id)

        # Extract usage info
        total_tokens = 0
        try:
            usage = result.usage()
            input_tokens = usage.request_tokens or 0
            output_tokens = usage.response_tokens or 0
            total_tokens = input_tokens + output_tokens

            model_obj = self.llm_agent.model
            model_name = getattr(model_obj, "model_name", str(model_obj))[:100]
            await record_usage(
                session=session,
                task_id=task_id,
                agent_id=self.agent_id,
                model_name=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=calculate_cost(model_name, input_tokens, output_tokens),
            )
        except Exception as exc:
            logger.warning(
                "usage_tracking_failed",
                task_id=task_id,
                error=str(exc),
            )

        logger.info(
            "analyst_task_completed",
            task_id=task_id,
            trace_id=trace_id,
            tokens_used=total_tokens,
        )

        return AgentResponse(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={},
            status="success",
            output={"result": result.output},
            tokens_used=total_tokens,
        )

    async def _run_with_retry(self, user_message: str, task_id: str) -> object:
        """Run LLM agent with retry logic for transient errors."""
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                return await self.llm_agent.run(user_message)
            except Exception as exc:
                last_error = exc
                error_str = str(exc)

                if "429" in error_str or "rate_limit" in error_str.lower():
                    backoff = _RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)]
                    logger.warning(
                        "rate_limit_retry",
                        task_id=task_id,
                        attempt=attempt + 1,
                        backoff_seconds=backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue

                if "tool_use_failed" in error_str or "tool call validation" in error_str:
                    logger.warning(
                        "tool_call_failed_retry_without_tools",
                        task_id=task_id,
                        attempt=attempt + 1,
                    )
                    no_tools_agent = PydanticAgent(
                        model=self.llm_agent.model,
                        system_prompt=(
                            "You are a research analyst. "
                            "Answer the question directly without using any tools."
                        ),
                    )
                    return await no_tools_agent.run(user_message)

                raise

        raise last_error  # type: ignore[misc]
