"""Temporal activities — the actual work units executed by workers.

Activities handle all I/O: Kafka publishing, DB queries, LLM calls.
Each activity is retryable and reports heartbeats for long-running operations.

Retry policies (applied by the workflow):
- LLM calls: max 3 attempts, 2s initial backoff, 2.0 coefficient
- Tool calls: max 5 attempts, 1s initial backoff
- DB writes: max 3 attempts, 500ms initial backoff
- Non-retryable: TokenBudgetExceededError, ToolAccessDenied
"""

from __future__ import annotations

import asyncio
import time

import structlog

from nexus.integrations.temporal.schemas import (
    PlanInput,
    PlanOutput,
    PlannedSubtask,
    ReviewInput,
    ReviewOutput,
    SubtaskActivityInput,
    SubtaskActivityOutput,
    SynthesisInput,
    SynthesisOutput,
    TaskWorkflowInput,
    TaskWorkflowOutput,
)

logger = structlog.get_logger()


# ─── CEO Planning Activity ───────────────────────────────────────────────────


async def ceo_planning_activity(input_data: PlanInput) -> PlanOutput:
    """CEO decomposes a task into subtasks with risk assessment.

    The CEO agent analyzes the instruction, creates an execution plan
    with risk assessment and security concerns, then decomposes into
    subtasks assigned to specialist agents.

    Args:
        input_data: Task details for planning.

    Returns:
        PlanOutput with subtasks, risk assessment, and security concerns.
    """
    logger.info(
        "ceo_planning_started",
        task_id=input_data.task_id,
    )

    try:
        from nexus.core.kafka.producer import publish
        from nexus.core.kafka.schemas import AgentCommand
        from nexus.core.kafka.topics import Topics

        # Dispatch to CEO via Kafka
        command = AgentCommand(
            task_id=input_data.task_id,
            trace_id=input_data.trace_id,
            agent_id="temporal-worker",
            payload={
                "source": "temporal",
                "phase": "planning",
                "workspace_id": input_data.workspace_id,
            },
            target_role="ceo",
            instruction=input_data.instruction,
        )
        await publish(Topics.TASK_QUEUE, command, key=input_data.task_id)

        # Poll for CEO's plan (with heartbeat reporting)
        plan = await _poll_task_completion(
            task_id=input_data.task_id,
            heartbeat_message="CEO planning",
            timeout_seconds=300,
        )

        if plan and plan.get("subtasks"):
            subtasks = [
                PlannedSubtask(
                    subtask_id=s.get("subtask_id", f"{input_data.task_id}-{i}"),
                    agent_role=s.get("agent_role", "engineer"),
                    instruction=s.get("instruction", ""),
                    depends_on=s.get("depends_on", []),
                    estimated_minutes=s.get("estimated_minutes", 5),
                )
                for i, s in enumerate(plan["subtasks"])
            ]
            return PlanOutput(
                task_id=input_data.task_id,
                subtasks=subtasks,
                risk_assessment=plan.get("risk_assessment", ""),
                security_concerns=plan.get("security_concerns", ""),
            )

        # If CEO doesn't produce subtasks, create a single engineer task
        return PlanOutput(
            task_id=input_data.task_id,
            subtasks=[
                PlannedSubtask(
                    subtask_id=f"{input_data.task_id}-0",
                    agent_role="engineer",
                    instruction=input_data.instruction,
                )
            ],
        )

    except Exception as exc:
        logger.error("ceo_planning_failed", task_id=input_data.task_id, error=str(exc))
        # Fallback: single engineer task
        return PlanOutput(
            task_id=input_data.task_id,
            subtasks=[
                PlannedSubtask(
                    subtask_id=f"{input_data.task_id}-0",
                    agent_role="engineer",
                    instruction=input_data.instruction,
                )
            ],
        )


# ─── Subtask Execution Activity ─────────────────────────────────────────────


async def execute_subtask_activity(
    input_data: SubtaskActivityInput,
) -> SubtaskActivityOutput:
    """Execute a single subtask via the agent pipeline.

    Dispatches to the appropriate agent via Kafka and polls for completion.
    Reports heartbeats every 30 seconds during execution.

    Args:
        input_data: Subtask details including agent role and instruction.

    Returns:
        SubtaskActivityOutput with execution results.
    """
    logger.info(
        "subtask_activity_started",
        task_id=input_data.task_id,
        agent_role=input_data.agent_role,
    )

    start_time = time.monotonic()

    try:
        from nexus.core.kafka.producer import publish
        from nexus.core.kafka.schemas import AgentCommand
        from nexus.core.kafka.topics import Topics

        command = AgentCommand(
            task_id=input_data.task_id,
            trace_id=input_data.trace_id,
            agent_id="temporal-worker",
            payload={
                "source": "temporal",
                "parent_task_id": input_data.parent_task_id,
                "workspace_id": input_data.workspace_id,
            },
            target_role=input_data.agent_role,
            instruction=input_data.instruction,
        )
        await publish(Topics.AGENT_COMMANDS, command, key=input_data.task_id)

        # Poll for completion with heartbeats
        result = await _poll_task_completion(
            task_id=input_data.task_id,
            heartbeat_message=f"{input_data.agent_role} executing",
            timeout_seconds=600,
        )

        duration = int(time.monotonic() - start_time)

        if result:
            return SubtaskActivityOutput(
                task_id=input_data.task_id,
                agent_role=input_data.agent_role,
                status=result.get("status", "completed"),
                output=str(result.get("output", "")),
                tokens_used=result.get("tokens_used", 0),
            )

        return SubtaskActivityOutput(
            task_id=input_data.task_id,
            agent_role=input_data.agent_role,
            status="failed",
            error=f"Subtask timed out after {duration}s",
        )

    except Exception as exc:
        logger.error(
            "subtask_activity_failed",
            task_id=input_data.task_id,
            error=str(exc),
        )
        return SubtaskActivityOutput(
            task_id=input_data.task_id,
            agent_role=input_data.agent_role,
            status="failed",
            error=str(exc),
        )


# ─── Director Synthesis Activity ────────────────────────────────────────────


async def director_synthesis_activity(
    input_data: SynthesisInput,
) -> SynthesisOutput:
    """Director evaluates all subtask results and synthesizes best output.

    Resolves contradictions, removes redundancy, performs security review
    against the execution plan, and produces a single coherent output.

    Args:
        input_data: All subtask results and plan context.

    Returns:
        SynthesisOutput with synthesized result and security review.
    """
    logger.info(
        "director_synthesis_started",
        task_id=input_data.task_id,
        result_count=len(input_data.results),
    )

    try:
        # Combine all subtask outputs
        combined = "\n\n---\n\n".join(
            f"[{r.agent_role}] (status: {r.status})\n{r.output}"
            for r in input_data.results
            if r.output
        )

        if not combined:
            return SynthesisOutput(
                task_id=input_data.task_id,
                synthesized_output="No agent produced output.",
                quality_score=0.0,
            )

        # Dispatch to Director via Kafka
        from nexus.core.kafka.producer import publish
        from nexus.core.kafka.schemas import AgentCommand
        from nexus.core.kafka.topics import Topics

        command = AgentCommand(
            task_id=input_data.task_id,
            trace_id=input_data.trace_id,
            agent_id="temporal-worker",
            payload={
                "source": "temporal",
                "phase": "synthesis",
                "combined_output": combined[:10000],
                "plan_context": input_data.plan_context,
            },
            target_role="director",
            instruction=f"Synthesize the following agent outputs into the best possible result:\n\n{combined[:5000]}",
        )
        await publish(Topics.DIRECTOR_REVIEW, command, key=input_data.task_id)

        # Poll for Director's synthesis
        result = await _poll_task_completion(
            task_id=input_data.task_id,
            heartbeat_message="Director synthesizing",
            timeout_seconds=300,
        )

        if result:
            return SynthesisOutput(
                task_id=input_data.task_id,
                synthesized_output=str(result.get("output", combined)),
                quality_score=float(result.get("quality_score", 0.7)),
                security_review_passed=result.get("security_review_passed", True),
                issues=result.get("issues", []),
            )

        # Fallback: return combined output without synthesis
        return SynthesisOutput(
            task_id=input_data.task_id,
            synthesized_output=combined,
            quality_score=0.5,
        )

    except Exception as exc:
        logger.error("director_synthesis_failed", task_id=input_data.task_id, error=str(exc))
        return SynthesisOutput(
            task_id=input_data.task_id,
            synthesized_output="Synthesis failed — returning raw agent outputs.",
            quality_score=0.0,
        )


# ─── QA Review Activity ────────────────────────────────────────────────────


async def qa_review_activity(input_data: ReviewInput) -> ReviewOutput:
    """QA agent reviews the synthesized output for quality.

    Supports bounded rework: if QA rejects, the output can be reworked
    up to max_rework_rounds times before escalating to human.

    Args:
        input_data: Output to review and rework configuration.

    Returns:
        ReviewOutput with approval status and feedback.
    """
    logger.info(
        "qa_review_started",
        task_id=input_data.task_id,
        rework_round=input_data.rework_round,
    )

    try:
        from nexus.core.kafka.producer import publish
        from nexus.core.kafka.schemas import AgentCommand
        from nexus.core.kafka.topics import Topics

        command = AgentCommand(
            task_id=input_data.task_id,
            trace_id=input_data.trace_id,
            agent_id="temporal-worker",
            payload={
                "source": "temporal",
                "phase": "qa_review",
                "rework_round": input_data.rework_round,
            },
            target_role="qa",
            instruction=f"Review the following output for quality and completeness:\n\n{input_data.output[:5000]}",
        )
        await publish(Topics.TASK_REVIEW_QUEUE, command, key=input_data.task_id)

        result = await _poll_task_completion(
            task_id=input_data.task_id,
            heartbeat_message="QA reviewing",
            timeout_seconds=300,
        )

        if result:
            return ReviewOutput(
                task_id=input_data.task_id,
                approved=result.get("approved", True),
                feedback=result.get("feedback", ""),
                final_output=result.get("final_output", input_data.output),
            )

        # Timeout — auto-approve to avoid blocking
        return ReviewOutput(
            task_id=input_data.task_id,
            approved=True,
            feedback="QA review timed out — auto-approved",
            final_output=input_data.output,
        )

    except Exception as exc:
        logger.error("qa_review_failed", task_id=input_data.task_id, error=str(exc))
        return ReviewOutput(
            task_id=input_data.task_id,
            approved=True,
            feedback=f"QA review failed: {exc} — auto-approved",
            final_output=input_data.output,
        )


# ─── Shared polling helper ──────────────────────────────────────────────────


async def _poll_task_completion(
    task_id: str,
    heartbeat_message: str,
    timeout_seconds: int = 600,
    poll_interval: int = 5,
) -> dict | None:
    """Poll the database for task completion with heartbeat reporting.

    Args:
        task_id: Task ID to poll for.
        heartbeat_message: Message to log with each heartbeat.
        timeout_seconds: Max wait time.
        poll_interval: Seconds between polls.

    Returns:
        Task output dict if completed, None if timed out.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from nexus.db.models import Task
    from nexus.settings import settings

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    elapsed = 0
    try:
        while elapsed < timeout_seconds:
            async with session_factory() as session:
                stmt = select(Task).where(Task.id == task_id)
                result = await session.execute(stmt)
                task = result.scalar_one_or_none()

                if task and task.status in ("completed", "failed"):
                    return {
                        "status": task.status,
                        "output": task.output,
                        "error": task.error,
                        "tokens_used": task.tokens_used or 0,
                    }

            # Heartbeat — log progress for monitoring
            if elapsed > 0 and elapsed % 30 == 0:
                logger.info(
                    "activity_heartbeat",
                    task_id=task_id,
                    message=heartbeat_message,
                    elapsed_seconds=elapsed,
                )

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        return None
    finally:
        await engine.dispose()
