"""Typed persisted execution identity, quota, lease and effect boundaries."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from nexus.company.contracts.base import Contract, Name
from nexus.company.contracts.results import ActionReceipt, VerificationResult
from nexus.company.contracts.work import WorkItem
from nexus.harness.limits import LoopCounters

AttemptKind = Literal["model_requests", "tool_attempts", "rework_rounds", "plan_revisions"]
ExecutionState = Literal[
    "eligible", "running", "awaiting_approval", "outcome_unknown", "verifying", "blocked"
]
EffectState = Literal["intent", "outcome_unknown", "succeeded", "failed"]


class ExecutionDeniedError(ValueError):
    """Current registered scope, identity, quota, fence or effect does not permit mutation."""


class AttemptQuota(BaseModel):
    """Lifetime per-kind maxima; child slices may intentionally have zero allowance."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    model_requests: int = Field(default=12, ge=0, le=12, strict=True)
    tool_attempts: int = Field(default=20, ge=0, le=20, strict=True)
    rework_rounds: int = Field(default=2, ge=0, le=2, strict=True)
    plan_revisions: int = Field(default=2, ge=0, le=2, strict=True)


class ExecutionRegistration(BaseModel):
    """Server-authored logical run and frozen work/catalog contract, not new budget authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    work: WorkItem
    run_id: UUID
    workflow_name: Name
    workflow_version: Name
    model_profile: Name
    model_registry_version: Name
    quota: AttemptQuota


class ExecutionSnapshot(Contract):
    """Authoritative lifetime counters and current lease/state for registered work."""

    registration: ExecutionRegistration
    workspace_id: UUID
    actor_id: UUID
    parent_task_id: UUID | None
    state: ExecutionState
    counters: LoopCounters
    delegated: LoopCounters
    fence: int = Field(ge=0, strict=True)
    worker_id: UUID | None
    lease_principal_id: UUID | None
    expires_at: AwareDatetime | None
    segment_number: int = Field(ge=0, strict=True)
    segment_id: UUID | None
    waiting_action_id: UUID | None


class ExecutionLease(Contract):
    """Current fenced actor lease; possession alone grants no external authority."""

    task_id: UUID
    trace_id: UUID
    actor_id: UUID
    workspace_id: UUID
    run_id: UUID
    workflow_version: Name
    segment_id: UUID
    worker_id: UUID
    fence: int = Field(gt=0, strict=True)
    expires_at: AwareDatetime
    mode: Literal["execute", "reconcile"]


class EffectRecord(Contract):
    """Persisted exact effect intent and provider receipt, distinct from verified work."""

    action_id: UUID
    task_id: UUID
    trace_id: UUID
    run_id: UUID
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    intent_fence: int = Field(gt=0, strict=True)
    attempt_kind: AttemptKind
    state: EffectState
    created_at: AwareDatetime
    receipt: ActionReceipt | None
    verification: VerificationResult | None


class EffectStart(BaseModel):
    """Only a newly committed intent returns permission for one caller-owned invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    record: EffectRecord
    permit_external_call: bool
