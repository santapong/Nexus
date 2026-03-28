"""Director Agent — meeting moderator and result synthesizer (Phase 7).

The Director sits between specialist output and QA review. It serves two
critical functions:

1. **Loop prevention**: Monitors meeting room discussions for convergence,
   stagnation, and infinite loops. Terminates unproductive debates and
   forces resolution.

2. **Result synthesis**: After agents finish their work (via meeting or
   subtask aggregation), the Director evaluates all contributions and
   synthesizes the best possible output before sending to QA.

Flow:
  CEO aggregates subtask outputs → Director synthesizes best result → QA reviews

Subscribes to: director.review
Publishes to: task.review_queue (sends synthesized output to QA)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import structlog
from pydantic_ai import Agent as PydanticAgent
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.agents.base import AgentBase
from nexus.core.kafka.meeting import ConvergenceReport
from nexus.core.kafka.producer import publish
from nexus.core.kafka.schemas import AgentCommand, AgentResponse, KafkaMessage
from nexus.core.kafka.topics import Topics
from nexus.core.llm.usage import calculate_cost, record_usage
from nexus.db.models import AgentRole

logger = structlog.get_logger()

_MAX_RETRIES = 5
_RETRY_BACKOFF_SECONDS = [5.0, 10.0, 20.0, 30.0, 45.0]

# Maximum number of contributions the Director will evaluate
_MAX_CONTRIBUTIONS = 10


class DirectorAgent(AgentBase):
    """Director agent — synthesizes best result and prevents infinite loops."""

    async def handle_task(self, message: AgentCommand, session: AsyncSession) -> AgentResponse:
        """Evaluate aggregated outputs, synthesize, and route to QA.

        The Director receives aggregated output from the CEO and:
        1. Checks for meeting convergence data (if a meeting was involved)
        2. Evaluates the quality and completeness of each contribution
        3. Synthesizes the best consolidated output
        4. Routes the synthesized result to QA for final review
        """
        task_id = str(message.task_id)
        trace_id = str(message.trace_id)

        logger.info(
            "director_review_started",
            task_id=task_id,
            trace_id=trace_id,
        )

        aggregated_output = message.payload.get("aggregated_output", "")
        original_instruction = message.payload.get("original_instruction", "")
        subtask_count = message.payload.get("subtask_count", 0)
        convergence_data = message.payload.get("convergence_report")

        # If convergence data exists, log and include in synthesis context
        convergence_context = ""
        if convergence_data:
            report = ConvergenceReport.model_validate(convergence_data)
            convergence_context = self._format_convergence_context(report)
            logger.info(
                "director_convergence_data",
                task_id=task_id,
                is_looping=report.is_looping,
                is_stagnating=report.is_stagnating,
                is_converging=report.is_converging,
                recommendation=report.recommendation,
            )

        # Use LLM to synthesize the best result
        synthesized = await self._synthesize_result(
            task_id=task_id,
            original_instruction=original_instruction,
            aggregated_output=aggregated_output,
            convergence_context=convergence_context,
            session=session,
        )

        # Route synthesized result to QA
        qa_command = AgentCommand(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={
                "aggregated_output": synthesized,
                "original_instruction": original_instruction,
                "subtask_count": subtask_count,
                "original_role": "director",
                "director_synthesized": True,
            },
            target_role=AgentRole.QA.value,
            instruction=(
                f"Review the following Director-synthesized output for the task:\n\n"
                f"Original request: {original_instruction}\n\n"
                f"Synthesized output:\n{synthesized}"
            ),
        )
        await publish(Topics.TASK_REVIEW_QUEUE, qa_command, key=task_id)

        logger.info(
            "director_routed_to_qa",
            task_id=task_id,
            trace_id=trace_id,
        )

        return AgentResponse(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={},
            status="success",
            output={
                "action": "director_synthesized_and_sent_to_qa",
                "task_id": task_id,
                "subtask_count": subtask_count,
            },
            tokens_used=0,
        )

    async def _synthesize_result(
        self,
        *,
        task_id: str,
        original_instruction: str,
        aggregated_output: str,
        convergence_context: str,
        session: AsyncSession,
    ) -> str:
        """Use LLM to evaluate contributions and produce the best output.

        The Director prompt instructs the LLM to:
        - Identify the strongest contributions
        - Resolve contradictions between agents
        - Remove redundancy and repetition
        - Produce a single, coherent, high-quality output
        """
        synthesis_prompt = (
            "You are the Director of NEXUS. Multiple specialist agents have "
            "produced outputs for a task. Your job is to synthesize the BEST "
            "possible final output.\n\n"
            "## Instructions\n"
            "1. Evaluate each agent's contribution for quality, accuracy, and completeness\n"
            "2. Identify the strongest ideas and insights from each contribution\n"
            "3. Resolve any contradictions — prefer the most well-reasoned position\n"
            "4. Remove redundancy — don't repeat the same point from multiple agents\n"
            "5. Produce a single, coherent, polished output that represents the best work\n"
            "6. If contributions have significant gaps, note what's missing\n\n"
            "## Rules\n"
            "- Do NOT simply concatenate the outputs. Synthesize them.\n"
            "- Do NOT add information that no agent provided — only combine what exists.\n"
            "- Do NOT fabricate sources or data.\n"
            "- Preserve specific technical details, code, and citations from the best contribution.\n"
            "- If one agent's work is clearly superior, use it as the foundation and enhance.\n"
        )

        if convergence_context:
            synthesis_prompt += f"\n## Meeting Analysis\n{convergence_context}\n"

        user_message = (
            f"Original task: {original_instruction}\n\n"
            f"Agent contributions:\n{aggregated_output}"
        )

        try:
            result = await self._run_with_retry(
                f"{synthesis_prompt}\n\n{user_message}", task_id
            )

            # Record LLM usage
            try:
                usage = result.usage()
                input_tokens = usage.request_tokens or 0
                output_tokens = usage.response_tokens or 0
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
                logger.warning("director_usage_tracking_failed", task_id=task_id, error=str(exc))

            return result.output

        except Exception as exc:
            logger.error(
                "director_synthesis_failed",
                task_id=task_id,
                error=str(exc),
            )
            # Fallback: return aggregated output as-is if synthesis fails
            return aggregated_output

    def _format_convergence_context(self, report: ConvergenceReport) -> str:
        """Format convergence report for LLM context."""
        lines: list[str] = []

        if report.is_looping:
            lines.append(
                "WARNING: The meeting discussion was LOOPING — agents were "
                "repeating the same arguments. Focus on extracting the core "
                "insight from the first substantive round."
            )
        if report.is_stagnating:
            lines.append(
                "NOTE: The discussion stagnated — no new ideas were emerging. "
                "The earliest rounds likely contain the most valuable content."
            )
        if report.is_converging:
            lines.append(
                "GOOD: Agents were converging on a consensus. The final round "
                "likely represents the most refined version of the answer."
            )

        if report.similarity_scores:
            lines.append(
                f"Round-to-round similarity: {report.similarity_scores}"
            )
        if report.unique_ideas_per_round:
            lines.append(
                f"Unique ideas per round: {report.unique_ideas_per_round}"
            )

        lines.append(f"Recommendation: {report.recommendation} — {report.reason}")

        return "\n".join(lines)

    async def _run_with_retry(self, user_message: str, task_id: str) -> Any:
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
                            "You are a Director who synthesizes agent outputs. "
                            "Produce the best consolidated result."
                        ),
                    )
                    return await no_tools_agent.run(user_message)

                raise

        raise last_error  # type: ignore[misc]
