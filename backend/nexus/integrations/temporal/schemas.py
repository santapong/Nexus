"""Temporal workflow schemas — Pydantic models for workflow inputs/outputs."""

from __future__ import annotations

from pydantic import BaseModel


class TaskWorkflowInput(BaseModel):
    """Input for the main task execution workflow."""

    task_id: str
    trace_id: str
    instruction: str
    workspace_id: str | None = None
    estimated_duration_minutes: int = 0


class TaskWorkflowOutput(BaseModel):
    """Output from the main task execution workflow."""

    task_id: str
    status: str  # completed, failed
    output: dict[str, object] | None = None
    error: str | None = None
    tokens_used: int = 0
    duration_seconds: int = 0


class SubtaskActivityInput(BaseModel):
    """Input for a single subtask activity."""

    task_id: str
    trace_id: str
    agent_role: str
    instruction: str
    workspace_id: str | None = None


class SubtaskActivityOutput(BaseModel):
    """Output from a single subtask activity."""

    task_id: str
    agent_role: str
    status: str
    output: str = ""
    error: str | None = None
    tokens_used: int = 0
