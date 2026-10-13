"""Serializable attempt counters; durable storage/parent allocation are later boundaries."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoopLimits(BaseModel):
    """Positive maximum attempts for one logical work identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    model_requests: int = Field(default=12, gt=0)
    tool_attempts: int = Field(default=20, gt=0)
    rework_rounds: int = Field(default=2, gt=0)
    plan_revisions: int = Field(default=2, gt=0)


class LoopCounters(BaseModel):
    """Consumed attempts, including failures; serialization never resets values."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    model_requests: int = Field(default=0, ge=0)
    tool_attempts: int = Field(default=0, ge=0)
    rework_rounds: int = Field(default=0, ge=0)
    plan_revisions: int = Field(default=0, ge=0)


def consume_attempt(counters: LoopCounters, limits: LoopLimits, kind: str) -> LoopCounters:
    """Reserve an attempt before making a call, without a success-only refund."""
    if kind not in LoopCounters.model_fields:
        raise ValueError("Unknown attempt kind")
    used = getattr(counters, kind)
    if used >= getattr(limits, kind):
        raise ValueError(f"Logical work limit reached: {kind}")
    values = counters.model_dump()
    values[kind] = used + 1
    return LoopCounters.model_validate(values)
