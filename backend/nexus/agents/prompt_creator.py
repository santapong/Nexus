"""Prompt Creator Agent — meta-agent for improving other agents' prompts.

Reads episodic memory failures for a target agent, identifies patterns,
drafts improved prompts, benchmarks them, and proposes the best version
for human approval. Never auto-deploys — always requires approval.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.agents.base import AgentBase
from nexus.core.kafka.producer import publish
from nexus.core.kafka.schemas import AgentCommand, AgentResponse, KafkaMessage
from nexus.core.kafka.topics import Topics
from nexus.db.models import (
    EpisodicMemory,
    Prompt,
    PromptBenchmark,
    Task,
)

logger = structlog.get_logger()

# Minimum number of recent tasks to analyze
_MIN_TASKS_FOR_ANALYSIS = 10
# Failure rate threshold to trigger improvement (10%)
_FAILURE_RATE_THRESHOLD = 0.10


class PromptCreatorAgent(AgentBase):
    """Meta-agent that improves other agents' system prompts.

    Workflow:
    1. Receive improvement request (manual or auto-triggered)
    2. Read target agent's episodic memory for failure patterns
    3. Analyze common failure modes
    4. Draft improved prompt
    5. Benchmark against test cases
    6. Store proposed prompt (is_active=false)
    7. Request human approval — never auto-activates
    """

    async def handle_task(self, message: AgentCommand, session: AsyncSession) -> AgentResponse:
        """Handle a prompt improvement request.

        Args:
            message: Command with target_role in payload.
            session: Database session.

        Returns:
            AgentResponse with proposed prompt details.
        """
        task_id = str(message.task_id)
        trace_id = str(message.trace_id)
        target_role = message.payload.get("target_role", "")

        if not target_role:
            return AgentResponse(
                task_id=message.task_id,
                trace_id=message.trace_id,
                agent_id=self.agent_id,
                payload={},
                status="failed",
                error="Missing target_role in payload",
            )

        logger.info(
            "prompt_creator_starting",
            task_id=task_id,
            trace_id=trace_id,
            target_role=target_role,
        )

        # Step 1: Analyze failures for the target role
        analysis = await self._analyze_failures(session, target_role, task_id)

        if not analysis["has_issues"]:
            logger.info(
                "prompt_creator_no_issues",
                task_id=task_id,
                target_role=target_role,
            )
            return AgentResponse(
                task_id=message.task_id,
                trace_id=message.trace_id,
                agent_id=self.agent_id,
                payload={},
                status="success",
                output={
                    "action": "no_improvement_needed",
                    "target_role": target_role,
                    "failure_rate": analysis["failure_rate"],
                },
            )

        # Step 2: Get current active prompt
        current_prompt = await self._get_active_prompt(session, target_role)

        # Step 3: Use LLM to draft improved prompt
        proposed_content = await self._draft_improved_prompt(
            task_id=task_id,
            target_role=target_role,
            current_prompt=current_prompt,
            failure_analysis=analysis,
        )

        # Step 4: Get benchmarks for the target role
        benchmarks = await self._get_benchmarks(session, target_role)

        # Step 5: Score the proposed prompt (simplified — LLM self-eval)
        score = await self._benchmark_prompt(
            task_id=task_id,
            proposed_prompt=proposed_content,
            benchmarks=benchmarks,
        )

        # Step 6: Save proposed prompt to DB (NOT active)
        new_version = await self._get_next_version(session, target_role)
        proposed = Prompt(
            agent_role=target_role,
            version=new_version,
            content=proposed_content,
            benchmark_score=score,
            is_active=False,
            authored_by="prompt_creator_agent",
            notes=(
                f"Auto-generated. Failure rate: {analysis['failure_rate']:.1%}. "
                f"Common issues: {', '.join(analysis['common_issues'][:3])}"
            ),
        )
        session.add(proposed)
        await session.flush()

        # Step 7: Request human approval
        approval_msg = KafkaMessage(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={
                "reason": "prompt_improvement_proposal",
                "target_role": target_role,
                "prompt_id": str(proposed.id),
                "version": new_version,
                "benchmark_score": score,
                "failure_rate": analysis["failure_rate"],
            },
        )
        await publish(Topics.HUMAN_INPUT_NEEDED, approval_msg, key=task_id)

        logger.info(
            "prompt_creator_proposed",
            task_id=task_id,
            target_role=target_role,
            version=new_version,
            score=score,
        )

        return AgentResponse(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={},
            status="success",
            output={
                "action": "prompt_proposed",
                "target_role": target_role,
                "version": new_version,
                "benchmark_score": score,
                "prompt_id": str(proposed.id),
                "requires_approval": True,
            },
        )

    async def _analyze_failures(
        self,
        session: AsyncSession,
        target_role: str,
        task_id: str,
    ) -> dict[str, Any]:
        """Analyze recent episodic memory for failure patterns.

        Args:
            session: Database session.
            target_role: The role to analyze.
            task_id: Current task ID for logging.

        Returns:
            Dict with failure_rate, common_issues, has_issues.
        """
        # Get recent episodes for agents with the target role
        stmt = (
            select(EpisodicMemory)
            .join(
                Task,
                EpisodicMemory.task_id == func.cast(Task.id, func.text()),
            )
            .where(EpisodicMemory.outcome.in_(["failed", "partial"]))
            .order_by(EpisodicMemory.created_at.desc())
            .limit(50)
        )
        result = await session.execute(stmt)
        failures = result.scalars().all()

        # Get total recent tasks for the role
        total_stmt = (
            select(func.count(EpisodicMemory.id))
            .order_by(EpisodicMemory.created_at.desc())
            .limit(50)
        )
        total_result = await session.execute(total_stmt)
        total_count = total_result.scalar() or 1

        failure_rate = len(failures) / max(total_count, 1)

        # Extract common issues from failure contexts
        common_issues: list[str] = []
        for ep in failures[:20]:
            ctx = ep.full_context
            if isinstance(ctx, dict):
                error = ctx.get("error", "")
                if error and error not in common_issues:
                    common_issues.append(str(error)[:100])

        return {
            "failure_rate": failure_rate,
            "failure_count": len(failures),
            "total_count": total_count,
            "common_issues": common_issues[:10],
            "has_issues": failure_rate >= _FAILURE_RATE_THRESHOLD,
        }

    async def _get_active_prompt(self, session: AsyncSession, role: str) -> str:
        """Get the current active prompt for a role.

        Args:
            session: Database session.
            role: The agent role.

        Returns:
            The active prompt content, or empty string if none.
        """
        stmt = (
            select(Prompt)
            .where(Prompt.agent_role == role, Prompt.is_active.is_(True))
            .order_by(Prompt.version.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        prompt = result.scalar_one_or_none()
        return prompt.content if prompt else ""

    async def _draft_improved_prompt(
        self,
        task_id: str,
        target_role: str,
        current_prompt: str,
        failure_analysis: dict[str, Any],
    ) -> str:
        """Use LLM to draft an improved prompt.

        Args:
            task_id: Current task ID for logging.
            target_role: The role being improved.
            current_prompt: The current active prompt.
            failure_analysis: Analysis of failure patterns.

        Returns:
            The improved prompt text.
        """
        issues_str = "\n".join(f"- {issue}" for issue in failure_analysis["common_issues"])

        improvement_prompt = (
            f"You are improving the system prompt for the '{target_role}' agent.\n\n"
            f"Current prompt:\n```\n{current_prompt}\n```\n\n"
            f"Failure rate: {failure_analysis['failure_rate']:.1%} "
            f"({failure_analysis['failure_count']} failures)\n\n"
            f"Common failure patterns:\n{issues_str}\n\n"
            f"Write an improved system prompt that addresses these failures.\n"
            f"Keep the same role and responsibilities but add:\n"
            f"- Specific guidance to avoid the identified failure patterns\n"
            f"- Clearer output format instructions\n"
            f"- Better error handling guidance\n\n"
            f"Return ONLY the improved prompt text, no explanation."
        )

        try:
            result = await self.llm_agent.run(improvement_prompt)
            return result.output.strip()
        except Exception as exc:
            logger.error(
                "prompt_draft_failed",
                task_id=task_id,
                target_role=target_role,
                error=str(exc),
            )
            return current_prompt  # Fallback to current

    async def _get_benchmarks(self, session: AsyncSession, role: str) -> list[dict[str, Any]]:
        """Get benchmark test cases for a role.

        Args:
            session: Database session.
            role: The agent role.

        Returns:
            List of benchmark dicts with input and expected_criteria.
        """
        stmt = select(PromptBenchmark).where(PromptBenchmark.agent_role == role)
        result = await session.execute(stmt)
        benchmarks = result.scalars().all()

        return [
            {
                "input": b.input,
                "expected_criteria": b.expected_criteria,
            }
            for b in benchmarks
        ]

    async def _benchmark_prompt(
        self,
        task_id: str,
        proposed_prompt: str,
        benchmarks: list[dict[str, Any]],
    ) -> float:
        """Score a proposed prompt against benchmarks.

        Uses LLM self-evaluation for v1. Returns a score 0.0-1.0.

        Args:
            task_id: Current task ID for logging.
            proposed_prompt: The prompt to benchmark.
            benchmarks: List of test cases.

        Returns:
            Score between 0.0 and 1.0.
        """
        if not benchmarks:
            return 0.5  # No benchmarks = neutral score

        benchmark_str = json.dumps(benchmarks[:5], indent=2)

        eval_prompt = (
            f"Evaluate this system prompt against the benchmark test cases.\n\n"
            f"System prompt:\n```\n{proposed_prompt[:2000]}\n```\n\n"
            f"Benchmark test cases:\n{benchmark_str}\n\n"
            f"Score the prompt from 0.0 to 1.0 based on how well it would "
            f"guide an agent to handle these test cases.\n"
            f"Return ONLY a decimal number between 0.0 and 1.0."
        )

        try:
            result = await self.llm_agent.run(eval_prompt)
            raw = result.output.strip()
            score = float(raw)
            return max(0.0, min(1.0, score))
        except (ValueError, Exception) as exc:
            logger.warning(
                "benchmark_scoring_failed",
                task_id=task_id,
                error=str(exc),
            )
            return 0.5  # Default neutral score

    async def _get_next_version(self, session: AsyncSession, role: str) -> int:
        """Get the next version number for a role's prompt.

        Args:
            session: Database session.
            role: The agent role.

        Returns:
            Next version number (current max + 1).
        """
        stmt = select(func.max(Prompt.version)).where(Prompt.agent_role == role)
        result = await session.execute(stmt)
        max_version = result.scalar() or 0
        return max_version + 1
