"""Eval scoring schemas — data models for LLM-as-judge evaluation."""
from __future__ import annotations

from pydantic import BaseModel, Field


class EvalDimensions(BaseModel):
    """Scoring dimensions for output quality evaluation."""

    relevance: float = Field(ge=0.0, le=1.0)
    completeness: float = Field(ge=0.0, le=1.0)
    accuracy: float = Field(ge=0.0, le=1.0)
    formatting: float = Field(ge=0.0, le=1.0)


class EvalScoreResult(BaseModel):
    """Result of evaluating a single task output."""

    task_id: str
    overall_score: float = Field(ge=0.0, le=1.0)
    dimensions: EvalDimensions
    judge_reasoning: str
    judge_model: str


class EvalSummary(BaseModel):
    """Aggregate eval scores for a batch run."""

    total_evaluated: int
    mean_score: float
    by_role: dict[str, float]
    by_model: dict[str, float]
