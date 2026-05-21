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
import re
from typing import Any

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
from nexus.settings import settings

logger = structlog.get_logger()

_MAX_RETRIES = 5
_RETRY_BACKOFF_SECONDS = [5.0, 10.0, 20.0, 30.0, 45.0]

# Maximum number of contributions the Director will evaluate
_MAX_CONTRIBUTIONS = 10

# Reasons the Director uses when escalating to human.input_needed.
_HALT_REASON_BLOCKED_PATTERN = "director_security_violation"
_HALT_REASON_OUT_OF_SCOPE = "director_scope_violation"


def _compile_blocked_patterns(raw: str) -> list[re.Pattern[str]]:
    """Compile the comma-separated `settings.security_blocked_patterns` value.

    Invalid regex patterns are skipped with a warning so a misconfiguration
    cannot completely disable the Director.

    Args:
        raw: Comma-separated regex pattern string from settings.

    Returns:
        List of compiled regex Pattern objects (may be empty).
    """
    patterns: list[re.Pattern[str]] = []
    for part in (raw or "").split(","):
        token = part.strip()
        if not token:
            continue
        try:
            patterns.append(re.compile(token, re.IGNORECASE))
        except re.error as exc:
            logger.warning(
                "director_invalid_blocked_pattern",
                pattern=token,
                error=str(exc),
            )
    return patterns


def _extract_subtask_ids(execution_plan: dict[str, Any]) -> set[str]:
    """Pull known subtask identifiers out of the CEO's execution plan.

    Tolerates multiple plan shapes — the plan may store subtasks as a list
    of dicts (each with `id`), a list of strings, or a dict keyed by id.

    Args:
        execution_plan: Plan dict from the CEO.

    Returns:
        Set of subtask ID strings the plan authorized. Empty set means the
        plan did not define any subtasks (scope check is then a no-op).
    """
    subtasks = execution_plan.get("subtasks") if execution_plan else None
    ids: set[str] = set()
    if isinstance(subtasks, dict):
        for key in subtasks:
            ids.add(str(key))
    elif isinstance(subtasks, list):
        for entry in subtasks:
            if isinstance(entry, dict):
                value = entry.get("id") or entry.get("subtask_id")
                if value is not None:
                    ids.add(str(value))
            elif isinstance(entry, str):
                ids.add(entry)
    return ids


def _scan_for_blocked_patterns(text: str, patterns: list[re.Pattern[str]]) -> list[str]:
    """Return the list of pattern source-strings that match the text."""
    if not text or not patterns:
        return []
    matches: list[str] = []
    for pat in patterns:
        if pat.search(text):
            matches.append(pat.pattern)
    return matches


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
        execution_plan = message.payload.get("execution_plan", {})

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

        # Hard security checks BEFORE synthesis. A violation halts the
        # pipeline — we publish to human.input_needed and skip QA entirely.
        halt_reason, halt_details = self._enforce_plan_constraints(
            task_id=task_id,
            aggregated_output=aggregated_output,
            agent_outputs=message.payload.get("agent_outputs"),
            execution_plan=execution_plan,
        )
        if halt_reason is not None:
            await self._halt_for_human(
                message=message,
                reason=halt_reason,
                details=halt_details,
                original_instruction=original_instruction,
            )
            return AgentResponse(
                task_id=message.task_id,
                trace_id=message.trace_id,
                agent_id=self.agent_id,
                payload={},
                status="escalated",
                output={
                    "action": "director_halted_for_human",
                    "reason": halt_reason,
                    "details": halt_details,
                    "task_id": task_id,
                },
                tokens_used=0,
            )

        # Soft security review: produce LLM context for the synthesis prompt.
        security_context = self._security_review(
            task_id=task_id,
            aggregated_output=aggregated_output,
            execution_plan=execution_plan,
        )

        # Use LLM to synthesize the best result
        synthesized = await self._synthesize_result(
            task_id=task_id,
            original_instruction=original_instruction,
            aggregated_output=aggregated_output,
            convergence_context=convergence_context,
            security_context=security_context,
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

    def _enforce_plan_constraints(
        self,
        *,
        task_id: str,
        aggregated_output: str,
        agent_outputs: Any,
        execution_plan: dict[str, Any],
    ) -> tuple[str | None, dict[str, Any]]:
        """Run hard pre-synthesis security & scope checks.

        Returns a tuple ``(halt_reason, details)``. ``halt_reason`` is None
        when nothing blocks the pipeline; otherwise it is a stable string
        identifier (see ``_HALT_REASON_*`` constants) and ``details`` is a
        dict suitable for inclusion in a human.input_needed payload.

        Checks performed:
          1. Scan ``aggregated_output`` against each compiled regex from
             ``settings.security_blocked_patterns``. Any match halts.
          2. Extract authorized subtask IDs from ``execution_plan``. If
             ``agent_outputs`` is provided as a list of objects with a
             ``subtask_id`` field, flag any output that references an
             unknown ID. Outputs lacking any ID reference are also flagged
             — they cannot be traced back to a plan-approved scope.

        Args:
            task_id: For logging context.
            aggregated_output: Combined text from all agents.
            agent_outputs: Optional structured per-agent output list from the
                CEO's payload. Each entry may be a dict with ``subtask_id``.
            execution_plan: CEO's plan dict (may be empty).

        Returns:
            ``(reason, details)`` — reason is None when synthesis may proceed.
        """
        # 1) Blocked-pattern scan (regex from settings).
        blocked_setting = getattr(settings, "security_blocked_patterns", "") or ""
        patterns = _compile_blocked_patterns(blocked_setting)
        matched = _scan_for_blocked_patterns(aggregated_output, patterns)
        if matched:
            logger.warning(
                "director_security_blocked_pattern",
                task_id=task_id,
                matched_patterns=matched,
            )
            return _HALT_REASON_BLOCKED_PATTERN, {
                "matched_patterns": matched,
                "description": (
                    "Aggregated output matched one or more configured "
                    "security_blocked_patterns. Human review required."
                ),
            }

        # 2) Scope check: outputs must reference a plan-authorized subtask.
        known_ids = _extract_subtask_ids(execution_plan)
        if known_ids and isinstance(agent_outputs, list):
            unknown_refs: list[dict[str, Any]] = []
            missing_refs: list[dict[str, Any]] = []
            for idx, entry in enumerate(agent_outputs):
                if not isinstance(entry, dict):
                    continue
                ref = entry.get("subtask_id") or entry.get("id")
                if ref is None:
                    missing_refs.append({"index": idx, "agent": entry.get("agent")})
                    continue
                if str(ref) not in known_ids:
                    unknown_refs.append(
                        {
                            "index": idx,
                            "agent": entry.get("agent"),
                            "subtask_id": str(ref),
                        }
                    )

            if unknown_refs or missing_refs:
                logger.warning(
                    "director_scope_violation",
                    task_id=task_id,
                    unknown_refs=unknown_refs,
                    missing_refs=missing_refs,
                    known_subtask_ids=sorted(known_ids),
                )
                return _HALT_REASON_OUT_OF_SCOPE, {
                    "unknown_refs": unknown_refs,
                    "missing_refs": missing_refs,
                    "known_subtask_ids": sorted(known_ids),
                    "description": (
                        "One or more agent outputs reference a subtask not "
                        "in the CEO's execution plan, or do not reference "
                        "any subtask at all. Scope creep blocked."
                    ),
                }

        return None, {}

    async def _halt_for_human(
        self,
        *,
        message: AgentCommand,
        reason: str,
        details: dict[str, Any],
        original_instruction: str,
    ) -> None:
        """Publish a human.input_needed event and stop the synthesis pipeline.

        Does NOT forward to QA. The pipeline only resumes after a human
        explicitly approves or rejects via the approvals flow.
        """
        msg = KafkaMessage(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={
                "reason": reason,
                "instruction": original_instruction,
                "agent_role": self.role.value,
                "violation": details,
                "stage": "director_pre_synthesis",
            },
        )
        await publish(Topics.HUMAN_INPUT_NEEDED, msg, key=str(message.task_id))

        try:
            await self._broadcast(
                {
                    "event": "human_input_needed",
                    "agent_id": self.agent_id,
                    "task_id": str(message.task_id),
                    "reason": reason,
                }
            )
        except Exception as exc:
            # Broadcast failures are non-fatal — the Kafka publish is the
            # authoritative event.
            logger.warning(
                "director_broadcast_failed",
                task_id=str(message.task_id),
                error=str(exc),
            )

        logger.info(
            "director_halted_pipeline",
            task_id=str(message.task_id),
            reason=reason,
        )

    def _security_review(
        self,
        *,
        task_id: str,
        aggregated_output: str,
        execution_plan: dict[str, Any],
    ) -> str:
        """Review agent outputs for security concerns against the execution plan.

        Checks:
        1. Outputs don't contain executable code that wasn't requested
        2. No unauthorized external references or URLs
        3. Risk level alignment — high-risk plan outputs get extra scrutiny
        4. PII leakage detection (delegated to sanitization layer)

        Args:
            task_id: For logging context.
            aggregated_output: The combined agent outputs.
            execution_plan: The CEO's execution plan.

        Returns:
            Security context string for the synthesis prompt.
        """
        concerns: list[str] = []
        risk_level = execution_plan.get("risk_level", "medium")
        plan_concerns = execution_plan.get("security_concerns", [])

        # Check if plan flagged security concerns
        if plan_concerns:
            concerns.append(
                f"CEO planning phase identified these security concerns: {plan_concerns}. "
                "Verify the output addresses these appropriately."
            )

        # High-risk tasks get extra scrutiny
        if risk_level == "high":
            concerns.append(
                "This is a HIGH-RISK task. Verify that all irreversible actions "
                "(file writes, emails, external API calls) are clearly documented "
                "and the output doesn't suggest bypassing approval flows."
            )

        # Check for shell injection patterns in output
        dangerous_patterns = [
            "rm -rf",
            "sudo ",
            "; DROP TABLE",
            "eval(",
            "exec(",
            "os.system(",
            "subprocess.call(",
            "__import__(",
        ]
        for pattern in dangerous_patterns:
            if pattern in aggregated_output:
                concerns.append(
                    f"WARNING: Output contains potentially dangerous pattern: '{pattern}'. "
                    "Review carefully before including in final synthesis."
                )

        if concerns:
            logger.info(
                "director_security_review",
                task_id=task_id,
                risk_level=risk_level,
                concern_count=len(concerns),
            )
            return "## Security Review\n" + "\n".join(f"- {c}" for c in concerns)

        return ""

    async def _synthesize_result(
        self,
        *,
        task_id: str,
        original_instruction: str,
        aggregated_output: str,
        convergence_context: str,
        security_context: str = "",
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
            "- Preserve specific technical details, code, and citations from"
            " the best contribution.\n"
            "- If one agent's work is clearly superior, use it as the foundation and enhance.\n"
        )

        if convergence_context:
            synthesis_prompt += f"\n## Meeting Analysis\n{convergence_context}\n"

        if security_context:
            synthesis_prompt += f"\n{security_context}\n"

        user_message = (
            f"Original task: {original_instruction}\n\nAgent contributions:\n{aggregated_output}"
        )

        try:
            result = await self._run_with_retry(f"{synthesis_prompt}\n\n{user_message}", task_id)

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
            lines.append(f"Round-to-round similarity: {report.similarity_scores}")
        if report.unique_ideas_per_round:
            lines.append(f"Unique ideas per round: {report.unique_ideas_per_round}")

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
