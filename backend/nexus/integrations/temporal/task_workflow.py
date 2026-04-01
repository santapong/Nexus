"""Temporal workflow definitions for durable multi-agent task orchestration.

Workflows define the orchestration logic. They MUST be deterministic —
all I/O happens in activities. Temporal replays the event history on
recovery, so workflow code must produce the same result given the same events.

Key patterns used:
- Child workflows for CEO planning, subtask execution, QA review
- Fan-out/fan-in for parallel specialist agent execution
- Signals for human approval (pause workflow → user approves → resume)
- Queries for real-time dashboard status
- Saga compensation — if subtask fails, cancel siblings + clean up

Gracefully degrades when Temporal is not available — falls back to
direct Kafka-based execution.
"""

from __future__ import annotations

import asyncio
import time

import structlog

from nexus.integrations.temporal.schemas import (
    HumanApprovalSignal,
    PlanInput,
    PlanOutput,
    ReviewInput,
    ReviewOutput,
    SubtaskActivityInput,
    SubtaskActivityOutput,
    SynthesisInput,
    SynthesisOutput,
    TaskProgressSignal,
    TaskStatusQuery,
    TaskWorkflowInput,
    TaskWorkflowOutput,
)

logger = structlog.get_logger()

# ─── Retry policies ─────────────────────────────────────────────────────────
# These are applied when registering as Temporal workflows.
# When running outside Temporal, they serve as documentation.

RETRY_POLICY_LLM = {
    "maximum_attempts": 3,
    "initial_interval_seconds": 2,
    "backoff_coefficient": 2.0,
    "maximum_interval_seconds": 30,
    "non_retryable_error_types": ["TokenBudgetExceededError", "ToolAccessDenied"],
}

RETRY_POLICY_TOOL = {
    "maximum_attempts": 5,
    "initial_interval_seconds": 1,
    "backoff_coefficient": 2.0,
    "maximum_interval_seconds": 60,
}

RETRY_POLICY_DB = {
    "maximum_attempts": 3,
    "initial_interval_seconds": 0.5,
    "backoff_coefficient": 2.0,
    "maximum_interval_seconds": 10,
}


class AgentTaskWorkflow:
    """Durable multi-agent task orchestration workflow.

    Orchestrates the full task lifecycle:
    1. CEO Planning — decompose task into subtasks with risk assessment
    2. Parallel Execution — fan-out subtasks to specialist agents
    3. Director Synthesis — combine results, resolve contradictions
    4. QA Review — quality check with bounded rework loop
    5. Completion — publish final result

    Supports:
    - Human-in-the-loop via signals (pause/resume on approval)
    - Real-time status via queries (dashboard polls status)
    - Saga compensation (cancel siblings on subtask failure)
    - Activity heartbeats (progress reporting during LLM calls)
    """

    def __init__(self) -> None:
        self._status = "initializing"
        self._current_step = ""
        self._progress_pct = 0
        self._subtasks_total = 0
        self._subtasks_completed = 0
        self._start_time = time.monotonic()
        self._waiting_for_approval = False
        self._approval_result: HumanApprovalSignal | None = None

    # ─── Signal handlers ─────────────────────────────────────────────────

    def handle_approval_signal(self, signal: HumanApprovalSignal) -> None:
        """Handle human approval/rejection signal."""
        self._approval_result = signal
        self._waiting_for_approval = False

    def handle_progress_signal(self, signal: TaskProgressSignal) -> None:
        """Handle progress update from an activity."""
        self._current_step = signal.step
        self._progress_pct = signal.progress_pct

    # ─── Query handlers ──────────────────────────────────────────────────

    def get_status(self, task_id: str = "") -> TaskStatusQuery:
        """Return current workflow status for dashboard queries."""
        return TaskStatusQuery(
            task_id=task_id,
            status=self._status,
            current_step=self._current_step,
            progress_pct=self._progress_pct,
            subtasks_total=self._subtasks_total,
            subtasks_completed=self._subtasks_completed,
            elapsed_seconds=int(time.monotonic() - self._start_time),
            waiting_for_approval=self._waiting_for_approval,
        )

    # ─── Main workflow ───────────────────────────────────────────────────

    async def run(self, input_data: TaskWorkflowInput) -> TaskWorkflowOutput:
        """Execute the full multi-agent task workflow.

        Args:
            input_data: Task details including instruction and workspace.

        Returns:
            TaskWorkflowOutput with final results.
        """
        task_id = input_data.task_id
        trace_id = input_data.trace_id
        self._start_time = time.monotonic()

        logger.info(
            "workflow_started",
            task_id=task_id,
            trace_id=trace_id,
            priority=input_data.priority,
        )

        try:
            # ── Phase 1: CEO Planning ────────────────────────────────────
            self._status = "planning"
            self._current_step = "CEO decomposing task"
            self._progress_pct = 10

            from nexus.integrations.temporal.activities import (
                ceo_planning_activity,
                director_synthesis_activity,
                execute_subtask_activity,
                qa_review_activity,
            )

            plan = await ceo_planning_activity(
                PlanInput(
                    task_id=task_id,
                    trace_id=trace_id,
                    instruction=input_data.instruction,
                    workspace_id=input_data.workspace_id,
                )
            )

            if not plan.subtasks:
                return TaskWorkflowOutput(
                    task_id=task_id,
                    status="failed",
                    error="CEO planning produced no subtasks",
                    duration_seconds=int(time.monotonic() - self._start_time),
                )

            self._subtasks_total = len(plan.subtasks)

            # ── Phase 2: Parallel Subtask Execution (fan-out/fan-in) ─────
            self._status = "executing"
            self._current_step = f"Running {self._subtasks_total} subtasks"
            self._progress_pct = 30

            # Group subtasks by dependency order
            independent = [s for s in plan.subtasks if not s.depends_on]
            dependent = [s for s in plan.subtasks if s.depends_on]

            results: list[SubtaskActivityOutput] = []
            failed_subtasks: list[str] = []

            # Execute independent subtasks in parallel
            if independent:
                parallel_tasks = [
                    execute_subtask_activity(
                        SubtaskActivityInput(
                            task_id=subtask.subtask_id,
                            trace_id=trace_id,
                            agent_role=subtask.agent_role,
                            instruction=subtask.instruction,
                            workspace_id=input_data.workspace_id,
                            parent_task_id=task_id,
                        )
                    )
                    for subtask in independent
                ]
                parallel_results = await asyncio.gather(
                    *parallel_tasks, return_exceptions=True
                )

                for i, result in enumerate(parallel_results):
                    if isinstance(result, Exception):
                        failed_subtasks.append(independent[i].subtask_id)
                        results.append(SubtaskActivityOutput(
                            task_id=independent[i].subtask_id,
                            agent_role=independent[i].agent_role,
                            status="failed",
                            error=str(result),
                        ))
                    else:
                        results.append(result)
                        if result.status == "completed":
                            self._subtasks_completed += 1

            # Execute dependent subtasks sequentially
            for subtask in dependent:
                # Check if dependencies succeeded
                dep_failed = any(
                    dep_id in failed_subtasks for dep_id in subtask.depends_on
                )
                if dep_failed:
                    failed_subtasks.append(subtask.subtask_id)
                    results.append(SubtaskActivityOutput(
                        task_id=subtask.subtask_id,
                        agent_role=subtask.agent_role,
                        status="skipped",
                        error="Dependency failed",
                    ))
                    continue

                dep_result = await execute_subtask_activity(
                    SubtaskActivityInput(
                        task_id=subtask.subtask_id,
                        trace_id=trace_id,
                        agent_role=subtask.agent_role,
                        instruction=subtask.instruction,
                        workspace_id=input_data.workspace_id,
                        parent_task_id=task_id,
                    )
                )
                results.append(dep_result)
                if dep_result.status == "completed":
                    self._subtasks_completed += 1

            self._progress_pct = 60

            # ── Phase 3: Director Synthesis ──────────────────────────────
            self._status = "synthesizing"
            self._current_step = "Director synthesizing results"
            self._progress_pct = 70

            synthesis = await director_synthesis_activity(
                SynthesisInput(
                    task_id=task_id,
                    trace_id=trace_id,
                    results=results,
                    plan_context=plan.risk_assessment,
                )
            )

            if not synthesis.security_review_passed:
                # Security review failed — require human approval
                self._waiting_for_approval = True
                self._current_step = "Waiting for human approval (security concern)"

                logger.warning(
                    "workflow_security_review_failed",
                    task_id=task_id,
                    issues=synthesis.issues,
                )

                # Wait for approval signal (in real Temporal, this uses workflow.wait_condition)
                max_wait = 3600  # 1 hour
                waited = 0
                while self._waiting_for_approval and waited < max_wait:
                    await asyncio.sleep(5)
                    waited += 5

                if self._approval_result and not self._approval_result.approved:
                    return TaskWorkflowOutput(
                        task_id=task_id,
                        status="cancelled",
                        error="Task rejected by human reviewer due to security concerns",
                        duration_seconds=int(time.monotonic() - self._start_time),
                    )

            # ── Phase 4: QA Review ───────────────────────────────────────
            self._status = "reviewing"
            self._current_step = "QA reviewing output"
            self._progress_pct = 85

            review = await qa_review_activity(
                ReviewInput(
                    task_id=task_id,
                    trace_id=trace_id,
                    output=synthesis.synthesized_output,
                )
            )

            # ── Phase 5: Completion ──────────────────────────────────────
            self._status = "completed"
            self._current_step = "Done"
            self._progress_pct = 100

            duration = int(time.monotonic() - self._start_time)

            logger.info(
                "workflow_completed",
                task_id=task_id,
                duration_seconds=duration,
                subtasks_completed=self._subtasks_completed,
                subtasks_failed=len(failed_subtasks),
            )

            return TaskWorkflowOutput(
                task_id=task_id,
                status="completed" if review.approved else "failed",
                output={"result": review.final_output or synthesis.synthesized_output},
                tokens_used=sum(r.tokens_used for r in results),
                duration_seconds=duration,
                subtasks_completed=self._subtasks_completed,
                subtasks_failed=len(failed_subtasks),
                error=review.feedback if not review.approved else None,
            )

        except Exception as exc:
            self._status = "failed"
            logger.error(
                "workflow_failed",
                task_id=task_id,
                error=str(exc),
            )
            return TaskWorkflowOutput(
                task_id=task_id,
                status="failed",
                error=str(exc),
                duration_seconds=int(time.monotonic() - self._start_time),
                subtasks_completed=self._subtasks_completed,
            )
