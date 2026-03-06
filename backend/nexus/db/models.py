from __future__ import annotations

import enum
from datetime import datetime, timezone

from advanced_alchemy.base import UUIDAuditBase, UUIDBase
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship


class AgentRole(str, enum.Enum):
    CEO = "ceo"
    ENGINEER = "engineer"
    ANALYST = "analyst"
    WRITER = "writer"
    QA = "qa"
    PROMPT_CREATOR = "prompt_creator"


class TaskStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"


class TaskSource(str, enum.Enum):
    HUMAN = "human"
    A2A = "a2a"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class EpisodeOutcome(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    ESCALATED = "escalated"


# ─── Table 1: agents ─────────────────────────────────────────────────────────


class Agent(UUIDAuditBase):
    __tablename__ = "agents"

    role: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    tool_access: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    kafka_topics: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    token_budget_per_task: Mapped[int] = mapped_column(Integer, default=50_000)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    tasks: Mapped[list[Task]] = relationship(back_populates="assigned_agent", lazy="selectin")


# ─── Table 2: tasks ──────────────────────────────────────────────────────────


class Task(UUIDAuditBase):
    __tablename__ = "tasks"

    trace_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    parent_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id"), nullable=True
    )
    assigned_agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agents.id"), nullable=True
    )
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TaskStatus.QUEUED.value, index=True
    )
    source: Mapped[str] = mapped_column(
        String(20), default=TaskSource.HUMAN.value
    )
    source_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    assigned_agent: Mapped[Agent | None] = relationship(back_populates="tasks", lazy="selectin")
    parent_task: Mapped[Task | None] = relationship(remote_side="Task.id", lazy="selectin")


# ─── Table 3: episodic_memory ────────────────────────────────────────────────


class EpisodicMemory(UUIDBase):
    __tablename__ = "episodic_memory"

    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    full_context: Mapped[dict] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    tools_used: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    importance_score: Mapped[float] = mapped_column(Float, default=0.5)
    embedding = Column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


# ─── Table 4: semantic_memory ────────────────────────────────────────────────


class SemanticMemory(UUIDBase):
    __tablename__ = "semantic_memory"
    __table_args__ = (
        UniqueConstraint("agent_id", "namespace", "key", name="uq_semantic_agent_ns_key"),
    )

    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    embedding = Column(Vector(1536), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


# ─── Table 5: llm_usage ─────────────────────────────────────────────────────


class LLMUsage(UUIDBase):
    __tablename__ = "llm_usage"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


# ─── Table 6: audit_log ─────────────────────────────────────────────────────


class AuditLog(UUIDBase):
    __tablename__ = "audit_log"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


# ─── Table 7: human_approvals ───────────────────────────────────────────────


class HumanApproval(UUIDBase):
    __tablename__ = "human_approvals"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    action_description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=ApprovalStatus.PENDING.value, index=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)


# ─── Table 8: prompts ───────────────────────────────────────────────────────


class Prompt(UUIDBase):
    __tablename__ = "prompts"
    __table_args__ = (
        UniqueConstraint("agent_role", "version", name="uq_prompt_role_version"),
    )

    agent_role: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    benchmark_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    authored_by: Mapped[str] = mapped_column(String(50), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ─── Table 9: prompt_benchmarks ─────────────────────────────────────────────


class PromptBenchmark(UUIDBase):
    __tablename__ = "prompt_benchmarks"

    agent_role: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    input: Mapped[str] = mapped_column(Text, nullable=False)
    expected_criteria: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
