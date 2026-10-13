"""Strict synthetic scenarios and version-bound worker checkpoints."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.base import Name
from nexus.company.contracts.results import ActionReceipt, VerificationResult
from nexus.company.contracts.work import WorkItem
from nexus.harness.limits import LoopCounters, LoopLimits

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
WorkerPhase = Literal[
    "model_pending",
    "tool_ready",
    "awaiting_approval",
    "tool_inflight",
    "verifying",
    "completed",
    "failed",
    "outcome_unknown",
    "inconclusive",
    "limit_reached",
]
TERMINAL_PHASES: frozenset[WorkerPhase] = frozenset(
    {"completed", "failed", "outcome_unknown", "inconclusive", "limit_reached"}
)


class FakeScenario(BaseModel):
    """Predetermined model/tool/verification inputs, never executable provider output.

    Verification evidence here is synthetic. It does not establish live acceptance.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["nexus.fake-scenario.v1"] = "nexus.fake-scenario.v1"
    workflow_version: Name
    model_version: Name
    recorded_at: AwareDatetime
    work: WorkItem
    action: ActionProposal
    limits: LoopLimits
    model_output: Name
    requires_approval: bool
    model_fails: bool
    tool_outcome: Literal["succeeded", "failed", "outcome_unknown"]
    verification: VerificationResult

    @model_validator(mode="after")
    def matching_scope(self) -> Self:
        """Reject foreign identities, unsupported tools and dependent verification."""
        if (
            self.action.company_id != self.work.company_id
            or self.action.task_id != self.work.task_id
            or self.action.trace_id != self.work.trace_id
            or self.verification.company_id != self.work.company_id
            or self.verification.action_id != self.action.action_id
        ):
            raise ValueError("Scenario company/work/action identities do not match")
        if not self.action.tool.startswith("fake."):
            raise ValueError("Offline worker accepts only fake tools")
        if self.verification.verifier_id == self.action.actor_id:
            raise ValueError("Verification must be independent of the acting principal")
        if set(self.verification.criterion_ids) != set(self.work.acceptance):
            raise ValueError("Verification must cover the exact acceptance criteria")
        return self


class WorkerBinding(BaseModel):
    """Expected immutable logical identity and content/version binding for replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    company_id: UUID
    task_id: UUID
    trace_id: UUID
    run_id: UUID
    action_id: UUID
    workflow_version: Name
    model_version: Name
    work_hash: Digest
    action_hash: Digest
    scenario_hash: Digest


class CheckpointCounters(LoopCounters):
    """Every persisted counter is mandatory; absent values cannot become zero."""

    model_requests: int = Field(ge=0, strict=True)
    tool_attempts: int = Field(ge=0, strict=True)
    rework_rounds: int = Field(ge=0, strict=True)
    plan_revisions: int = Field(ge=0, strict=True)


class WorkerCheckpoint(BaseModel):
    """Trusted internal JSON snapshot, including consumed attempts and known results."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["nexus.worker-checkpoint.v1"] = "nexus.worker-checkpoint.v1"
    binding: WorkerBinding
    phase: WorkerPhase
    counters: CheckpointCounters
    segment_number: int = Field(ge=0)
    segment_id: UUID
    generated_output: Name | None
    approval_decision_id: UUID | None
    receipt: ActionReceipt | None
    verification: VerificationResult | None
    reason: Name | None

    @model_validator(mode="after")
    def valid_progress(self) -> Self:
        """Reject impossible progress and fail-closed completion without evidence."""
        if self.generated_output is not None and self.counters.model_requests < 1:
            raise ValueError("Generated output requires a consumed model attempt")
        if self.phase in {"tool_ready", "awaiting_approval", "tool_inflight", "verifying"} and (
            self.generated_output is None
        ):
            raise ValueError("Post-model progress requires generated output")
        if self.phase == "model_pending" and self.generated_output is not None:
            raise ValueError("Model-pending checkpoint already contains model output")
        if self.phase in {"tool_inflight", "outcome_unknown"} and (
            self.counters.tool_attempts < 1 or self.generated_output is None
        ):
            raise ValueError("Effect intent requires a consumed tool attempt")
        if self.receipt is not None:
            self._validate_receipt()
        if self.verification is not None:
            self._validate_verification()
        if self.phase == "verifying" and (
            self.receipt is None or self.receipt.outcome != "succeeded"
        ):
            raise ValueError("Verification requires a known successful receipt")
        if self.phase == "completed" and (
            self.verification is None or self.verification.verdict != "pass"
        ):
            raise ValueError("Completion requires passing independent verification")
        return self

    def _validate_receipt(self) -> None:
        receipt = self.receipt
        assert receipt is not None
        binding = self.binding
        if (
            self.generated_output is None
            or self.counters.tool_attempts < 1
            or (
                receipt.company_id,
                receipt.task_id,
                receipt.trace_id,
                receipt.action_id,
                receipt.proposal_hash,
            )
            != (
                binding.company_id,
                binding.task_id,
                binding.trace_id,
                binding.action_id,
                binding.action_hash,
            )
        ):
            raise ValueError("Receipt does not match checkpoint binding/counter")
        if self.phase in {"model_pending", "tool_ready", "awaiting_approval", "tool_inflight"}:
            raise ValueError("Receipt is incompatible with checkpoint phase")

    def _validate_verification(self) -> None:
        verification = self.verification
        assert verification is not None
        if self.receipt is None or self.receipt.outcome != "succeeded":
            raise ValueError("Verification requires a successful receipt")
        if (verification.company_id, verification.action_id) != (
            self.binding.company_id,
            self.binding.action_id,
        ):
            raise ValueError("Verification does not match checkpoint binding")


class CheckpointEnvelope(BaseModel):
    """Checksum for accidental corruption; not an authentication or MAC claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    checksum: Digest
    checkpoint: WorkerCheckpoint


class SegmentResult(BaseModel):
    """Completed offline invocation; approval waits never hold a worker segment."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    checkpoint: WorkerCheckpoint
    segment_released: Literal[True] = True
