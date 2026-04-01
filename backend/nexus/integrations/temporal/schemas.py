"""Temporal workflow schemas — Pydantic models for workflow inputs/outputs.

Includes schemas for the main task workflow, subtask activities,
human approval signals, real-time queries, and saga compensation.
"""

from __future__ import annotations

from pydantic import BaseModel


class TaskWorkflowInput(BaseModel):
    """Input for the main task execution workflow."""

    task_id: str
    trace_id: str
    instruction: str
    workspace_id: str | None = None
    estimated_duration_minutes: int = 0
    priority: str = "normal"  # low, normal, high, urgent


class TaskWorkflowOutput(BaseModel):
    """Output from the main task execution workflow."""

    task_id: str
    status: str  # completed, failed, cancelled
    output: dict[str, object] | None = None
    error: str | None = None
    tokens_used: int = 0
    duration_seconds: int = 0
    subtasks_completed: int = 0
    subtasks_failed: int = 0


class SubtaskActivityInput(BaseModel):
    """Input for a single subtask activity."""

    task_id: str
    trace_id: str
    agent_role: str
    instruction: str
    workspace_id: str | None = None
    parent_task_id: str | None = None


class SubtaskActivityOutput(BaseModel):
    """Output from a single subtask activity."""

    task_id: str
    agent_role: str
    status: str
    output: str = ""
    error: str | None = None
    tokens_used: int = 0


# ─── Planning schemas ─────────────────────────────────────────────────────────


class PlanInput(BaseModel):
    """Input for CEO planning phase."""

    task_id: str
    trace_id: str
    instruction: str
    workspace_id: str | None = None


class PlanOutput(BaseModel):
    """Output from CEO planning — decomposed subtasks."""

    task_id: str
    subtasks: list[PlannedSubtask] = []
    risk_assessment: str = ""
    security_concerns: str = ""


class PlannedSubtask(BaseModel):
    """A single subtask from the CEO's plan."""

    subtask_id: str
    agent_role: str
    instruction: str
    depends_on: list[str] = []  # subtask_ids this depends on
    estimated_minutes: int = 5


# ─── Synthesis schemas ────────────────────────────────────────────────────────


class SynthesisInput(BaseModel):
    """Input for Director synthesis activity."""

    task_id: str
    trace_id: str
    results: list[SubtaskActivityOutput] = []
    plan_context: str = ""


class SynthesisOutput(BaseModel):
    """Output from Director synthesis."""

    task_id: str
    synthesized_output: str = ""
    quality_score: float = 0.0
    security_review_passed: bool = True
    issues: list[str] = []


# ─── QA review schemas ───────────────────────────────────────────────────────


class ReviewInput(BaseModel):
    """Input for QA review workflow."""

    task_id: str
    trace_id: str
    output: str = ""
    rework_round: int = 0
    max_rework_rounds: int = 2


class ReviewOutput(BaseModel):
    """Output from QA review."""

    task_id: str
    approved: bool = False
    feedback: str = ""
    final_output: str = ""


# ─── Signal schemas ──────────────────────────────────────────────────────────


class HumanApprovalSignal(BaseModel):
    """Signal sent when a human approves or rejects a pending action."""

    approved: bool
    resolved_by: str = ""
    comment: str = ""


class TaskProgressSignal(BaseModel):
    """Signal to update task progress from an activity."""

    step: str
    progress_pct: int = 0
    message: str = ""


# ─── Query result schemas ───────────────────────────────────────────────────


class TaskStatusQuery(BaseModel):
    """Response to a task status query."""

    task_id: str
    status: str  # planning, executing, synthesizing, reviewing, completed, failed
    current_step: str = ""
    progress_pct: int = 0
    subtasks_total: int = 0
    subtasks_completed: int = 0
    elapsed_seconds: int = 0
    waiting_for_approval: bool = False


# Fix forward reference
PlanOutput.model_rebuild()
