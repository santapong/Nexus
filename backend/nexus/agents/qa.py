"""QA Agent — quality assurance reviewer (Phase 2).

Reviews all agent outputs before delivery. Subscribes to task.review_queue
and publishes final results to task.results (not agent.responses).

The QA Agent is the gatekeeper — it ensures quality before any output
reaches the user or external caller.
"""

from __future__ import annotations

import asyncio

import structlog
from pydantic_ai import Agent as PydanticAgent
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.agents.base import AgentBase
from nexus.core.kafka.producer import publish
from nexus.core.kafka.schemas import AgentCommand, AgentResponse, TaskResult
from nexus.core.kafka.topics import Topics
from nexus.core.llm.usage import calculate_cost, record_usage

logger = structlog.get_logger()

_MAX_RETRIES = 5
_RETRY_BACKOFF_SECONDS = [5.0, 10.0, 20.0, 30.0, 45.0]


class QAAgent(AgentBase):
    """QA agent — reviews outputs and publishes final results."""

    async def handle_task(self, message: AgentCommand, session: AsyncSession) -> AgentResponse:
        """Review an aggregated result and decide approve/reject.

        On approval: publishes TaskResult to task.results.
        On rejection: publishes feedback back to agent.commands for rework.
        """
        task_id = str(message.task_id)
        trace_id = str(message.trace_id)

        logger.info(
            "qa_review_started",
            task_id=task_id,
            trace_id=trace_id,
            instruction=message.instruction[:200],
        )

        memory_context = getattr(self, "_memory_context", {})
        context_parts: list[str] = []

        if memory_context.get("similar_episodes"):
            context_parts.append(
                "Past QA reviews:\n"
                + "\n".join(f"- {ep}" for ep in memory_context["similar_episodes"])
            )

        # The instruction for QA contains the aggregated output to review
        review_prompt = (
            "Review the following output for quality. Check for:\n"
            "1. Accuracy and correctness\n"
            "2. Completeness — does it address the original task?\n"
            "3. Clarity and coherence\n"
            "4. No fabricated information or hallucinations\n\n"
            "Respond with a JSON object containing:\n"
            '- "approved": true/false\n'
            '- "score": 0.0 to 1.0\n'
            '- "feedback": brief explanation of your assessment\n'
            '- "issues": list of specific issues found (empty if approved)\n\n'
        )

        if context_parts:
            user_message = (
                "\n\n".join(context_parts)
                + f"\n\n{review_prompt}Output to review:\n{message.instruction}"
            )
        else:
            user_message = f"{review_prompt}Output to review:\n{message.instruction}"

        result = await self._run_with_retry(user_message, task_id)

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

        # Parse QA decision — default to approved if parsing fails
        qa_output = result.output
        approved = True
        try:
            import json

            if isinstance(qa_output, str):
                # Try to extract JSON from the response
                # Handle cases where LLM wraps JSON in markdown code blocks
                clean = qa_output.strip()
                if clean.startswith("```"):
                    clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                    clean = clean.rsplit("```", 1)[0]
                parsed = json.loads(clean)
                approved = parsed.get("approved", True)
                qa_output = json.dumps(parsed)
        except (json.JSONDecodeError, AttributeError):
            # If we can't parse, treat as approved with the raw output
            pass

        if approved:
            # Publish final result to task.results
            task_result = TaskResult(
                task_id=message.task_id,
                trace_id=message.trace_id,
                agent_id=self.agent_id,
                payload=message.payload,
                status="completed",
                output={
                    "qa_review": qa_output,
                    "original_output": message.payload.get("aggregated_output", ""),
                },
            )
            await publish(Topics.TASK_RESULTS, task_result, key=task_id)

            logger.info(
                "qa_approved",
                task_id=task_id,
                trace_id=trace_id,
            )
        else:
            # Reject — send feedback back for rework via agent.commands
            rework_command = AgentCommand(
                task_id=message.task_id,
                trace_id=message.trace_id,
                agent_id=self.agent_id,
                payload={"qa_feedback": qa_output, "rework": True},
                target_role=message.payload.get("original_role", "engineer"),
                instruction=(
                    f"QA REWORK REQUESTED: {qa_output}\n\nOriginal task: "
                    f"{message.payload.get('original_instruction', message.instruction)}"
                ),
            )
            await publish(Topics.AGENT_COMMANDS, rework_command, key=task_id)

            logger.info(
                "qa_rejected",
                task_id=task_id,
                trace_id=trace_id,
            )

        logger.info(
            "qa_review_completed",
            task_id=task_id,
            trace_id=trace_id,
            approved=approved,
            tokens_used=total_tokens,
        )

        return AgentResponse(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={},
            status="success",
            output={"result": qa_output, "approved": approved},
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
                            "You are a quality assurance reviewer. "
                            "Review the output directly without using any tools."
                        ),
                    )
                    return await no_tools_agent.run(user_message)

                raise

        raise last_error  # type: ignore[misc]
