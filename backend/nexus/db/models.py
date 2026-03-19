from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any

from advanced_alchemy.base import UUIDAuditBase, UUIDBase
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship


class AgentRole(enum.StrEnum):
    CEO = "ceo"
    ENGINEER = "engineer"
    ANALYST = "analyst"
    WRITER = "writer"
    QA = "qa"
    PROMPT_CREATOR = "prompt_creator"


class TaskStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"


class TaskSource(enum.StrEnum):
    HUMAN = "human"
    A2A = "a2a"


class ApprovalStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class EpisodeOutcome(enum.StrEnum):
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
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )

    # Relationships
    tasks: Mapped[list[Task]] = relationship(back_populates="assigned_agent", lazy="raise")


# ─── Table 2: tasks ──────────────────────────────────────────────────────────


class Task(UUIDAuditBase):
    __tablename__ = "tasks"

    trace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    parent_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    assigned_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TaskStatus.QUEUED.value, index=True
    )
    source: Mapped[str] = mapped_column(String(20), default=TaskSource.HUMAN.value)
    source_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    schedule_id: Mapped[str | None] = mapped_column(
        ForeignKey("task_schedules.id"), nullable=True, index=True
    )
    rework_round: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    assigned_agent: Mapped[Agent | None] = relationship(back_populates="tasks", lazy="raise")
    parent_task: Mapped[Task | None] = relationship(remote_side="Task.id", lazy="raise")


# ─── Table 3: episodic_memory ────────────────────────────────────────────────


class EpisodicMemory(UUIDBase):
    __tablename__ = "episodic_memory"

    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    full_context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    tools_used: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    importance_score: Mapped[float] = mapped_column(Float, default=0.5)
    embedding = Column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
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
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
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
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


# ─── Table 6: audit_log ─────────────────────────────────────────────────────


class AuditLog(UUIDBase):
    __tablename__ = "audit_log"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
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
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)


# ─── Table 8: prompts ───────────────────────────────────────────────────────


class Prompt(UUIDBase):
    __tablename__ = "prompts"
    __table_args__ = (UniqueConstraint("agent_role", "version", name="uq_prompt_role_version"),)

    agent_role: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    benchmark_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    authored_by: Mapped[str] = mapped_column(String(50), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ─── Table 9: prompt_benchmarks ─────────────────────────────────────────────


class PromptBenchmark(UUIDBase):
    __tablename__ = "prompt_benchmarks"

    agent_role: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    input: Mapped[str] = mapped_column(Text, nullable=False)
    expected_criteria: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


# ─── Table 10: dead_letters ───────────────────────────────────────────────


class DeadLetter(UUIDBase):
    __tablename__ = "dead_letters"

    source_topic: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    message_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    raw_message: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ─── Table 11: a2a_tokens ─────────────────────────────────────────────────


class A2ATokenRecord(UUIDBase):
    __tablename__ = "a2a_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    allowed_skills: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=lambda: ["*"]
    )
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, default=60)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )


# ─── Table 12: eval_results ───────────────────────────────────────────────


class EvalResult(UUIDBase):
    __tablename__ = "eval_results"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    relevance: Mapped[float | None] = mapped_column(Float, nullable=True)
    completeness: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    formatting: Mapped[float | None] = mapped_column(Float, nullable=True)
    judge_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    judge_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


# ─── Table 13: users ─────────────────────────────────────────────────────────


class User(UUIDAuditBase):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    workspaces: Mapped[list[Workspace]] = relationship(back_populates="owner", lazy="raise")


# ─── Table 14: workspaces ───────────────────────────────────────────────────


class Workspace(UUIDAuditBase):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    daily_spend_limit_usd: Mapped[float] = mapped_column(Float, default=5.0)

    # Relationships
    owner: Mapped[User] = relationship(back_populates="workspaces", lazy="raise")


# ─── Table 15: workspace_members ─────────────────────────────────────────────


class WorkspaceMember(UUIDBase):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


# ─── Table 16: agent_listings (Marketplace) ─────────────────────────────


class AgentListing(UUIDAuditBase):
    __tablename__ = "agent_listings"

    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    skills: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    price_per_task_usd: Mapped[float] = mapped_column(Float, default=0.0)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rating: Mapped[float] = mapped_column(Float, default=0.0)
    total_reviews: Mapped[int] = mapped_column(Integer, default=0)
    total_tasks_completed: Mapped[int] = mapped_column(Integer, default=0)


# ─── Table 14: marketplace_reviews ───────────────────────────────────────


class MarketplaceReview(UUIDAuditBase):
    __tablename__ = "marketplace_reviews"

    listing_id: Mapped[str] = mapped_column(
        ForeignKey("agent_listings.id"), nullable=False, index=True
    )
    reviewer_workspace_id: Mapped[str] = mapped_column(String(100), nullable=False)
    rating: Mapped[float] = mapped_column(Float, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


# ─── Table 15: billing_records ───────────────────────────────────────────


class BillingRecord(UUIDAuditBase):
    __tablename__ = "billing_records"

    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    amount_usd: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    billing_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # llm_usage | tool_usage | a2a_hire


# ─── Table 19: oauth_accounts ───────────────────────────────────────────


class OAuthAccount(UUIDAuditBase):
    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # google | github | microsoft
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ─── Table 20: webhook_subscriptions ─────────────────────────────────────


class WebhookSubscription(UUIDAuditBase):
    __tablename__ = "webhook_subscriptions"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    events: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ─── Table 21: task_schedules (Phase 5 Track B) ────────────────────────────


class TaskSchedule(UUIDAuditBase):
    __tablename__ = "task_schedules"

    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    target_role: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    max_runs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)


# ─── Table 22: model_benchmarks (Phase 5 Track B) ──────────────────────────


class ModelBenchmark(UUIDBase):
    __tablename__ = "model_benchmarks"

    agent_role: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    benchmark_id: Mapped[str] = mapped_column(ForeignKey("prompt_benchmarks.id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


# ─── Table 23: provider_health (Phase 5 Track B) ───────────────────────────


class ProviderHealth(UUIDBase):
    __tablename__ = "provider_health"

    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # healthy|degraded|down
    latency_p50_ms: Mapped[int] = mapped_column(Integer, default=0)
    latency_p99_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_rate: Mapped[float] = mapped_column(Float, default=0.0)
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    total_errors: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


# ─── Table 24: agent_cost_alerts (Phase 5 Track B) ─────────────────────────


class AgentCostAlert(UUIDBase):
    __tablename__ = "agent_cost_alerts"

    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    daily_limit_usd: Mapped[float] = mapped_column(Float, nullable=False)
    alert_threshold_pct: Mapped[float] = mapped_column(Float, default=0.9)
    webhook_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


# ─── Table 25: feedback_signals (Phase 5 Track B — RLHF-lite) ───────────────


class FeedbackSignal(UUIDBase):
    __tablename__ = "feedback_signals"

    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # approval | rating | rework | escalation
    signal_value: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0–1.0
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


# ─── Table 26: fine_tuning_jobs (Phase 5 Track B) ────────────────────────────


class FineTuningJob(UUIDBase):
    __tablename__ = "fine_tuning_jobs"

    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    agent_role: Mapped[str] = mapped_column(String(50), nullable=False)
    base_model: Mapped[str] = mapped_column(String(100), nullable=False)
    target_model: Mapped[str] = mapped_column(String(100), nullable=False)
    dataset_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )  # pending | running | completed | failed
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


# ─── Table 27: plugin_registrations (Phase 5 Track C) ────────────────────────


class PluginRegistration(UUIDBase):
    __tablename__ = "plugin_registrations"

    plugin_id: Mapped[str] = mapped_column(String(500), nullable=False, unique=True, index=True)
    plugin_type: Mapped[str] = mapped_column(String(20), nullable=False)  # python | http
    source: Mapped[str] = mapped_column(String(500), nullable=False)  # module path or URL
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
