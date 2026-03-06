"""Engineer Agent — first full agent implementation (Phase 1).

Handles software engineering tasks: code generation, debugging,
research, file operations, and code execution.
"""
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.agents.base import AgentBase
from nexus.db.models import AgentRole
from nexus.kafka.schemas import AgentCommand, AgentResponse
from nexus.llm.usage import record_usage

logger = structlog.get_logger()


class EngineerAgent(AgentBase):
    """Engineer agent — executes coding and technical tasks."""

    async def handle_task(
        self, message: AgentCommand, session: AsyncSession
    ) -> AgentResponse:
        """Execute an engineering task using the Pydantic AI agent with tools."""
        task_id = str(message.task_id)
        trace_id = str(message.trace_id)

        logger.info(
            "engineer_task_started",
            task_id=task_id,
            trace_id=trace_id,
            instruction=message.instruction[:200],
        )

        # Build prompt context from loaded memory
        memory_context = getattr(self, "_memory_context", {})
        context_parts: list[str] = []

        if memory_context.get("similar_episodes"):
            context_parts.append(
                "Relevant past experience:\n"
                + "\n".join(f"- {ep}" for ep in memory_context["similar_episodes"])
            )

        if memory_context.get("working_memory"):
            context_parts.append(
                "Working memory:\n"
                + str(memory_context["working_memory"])
            )

        # Construct the user message
        if context_parts:
            user_message = "\n\n".join(context_parts) + f"\n\nTask: {message.instruction}"
        else:
            user_message = message.instruction

        # Run the Pydantic AI agent
        result = await self.llm_agent.run(user_message)

        # Extract usage info
        total_tokens = 0
        try:
            usage = result.usage()
            input_tokens = usage.request_tokens or 0
            output_tokens = usage.response_tokens or 0
            total_tokens = input_tokens + output_tokens

            await record_usage(
                session=session,
                task_id=task_id,
                agent_id=self.agent_id,
                model_name=str(self.llm_agent.model),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=0.0,  # TODO: calculate from model pricing
            )
        except Exception as exc:
            logger.warning(
                "usage_tracking_failed",
                task_id=task_id,
                error=str(exc),
            )

        logger.info(
            "engineer_task_completed",
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
            output={"result": result.data},
            tokens_used=total_tokens,
        )
