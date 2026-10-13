"""Deterministic offline execution segments with no provider or real tool I/O."""

from __future__ import annotations

from typing import Literal
from uuid import uuid5

from pydantic import JsonValue

from nexus.company.contracts.actions import ApprovalDecision
from nexus.company.contracts.results import ActionReceipt
from nexus.execution.checkpoint import segment_identity, validate_replay
from nexus.execution.contracts import (
    TERMINAL_PHASES,
    FakeScenario,
    SegmentResult,
    WorkerCheckpoint,
)
from nexus.harness.approvals import ApprovalContext, require_exact_approval
from nexus.harness.limits import consume_attempt

StopAt = Literal["after_model", "after_tool_intent", "after_receipt"]


def _replace(checkpoint: WorkerCheckpoint, **changes: JsonValue) -> WorkerCheckpoint:
    return WorkerCheckpoint.model_validate(checkpoint.model_dump(mode="json") | changes)


class FakeWorker:
    """Run one fixture and return on approval, stop point, failure or acceptance.

    This is a contract test harness, not a durable worker, sandbox, paid-model
    integration, action executor, approval ledger or production verifier.
    """

    def __init__(self, scenario: FakeScenario) -> None:
        self.scenario = FakeScenario.model_validate_json(scenario.model_dump_json())

    def run_segment(
        self,
        checkpoint: WorkerCheckpoint,
        *,
        approval: ApprovalDecision | None = None,
        context: ApprovalContext | None = None,
        stop_at: StopAt | None = None,
    ) -> SegmentResult:
        """Release each segment, preserving counters and stopping unknown replay."""
        current = validate_replay(
            checkpoint,
            scenario=self.scenario,
            expected_run_id=checkpoint.binding.run_id,
            minimum_counters=checkpoint.counters,
        )
        if current.phase in TERMINAL_PHASES or (
            current.phase == "awaiting_approval" and approval is None
        ):
            return SegmentResult(checkpoint=current)
        current = self._next_segment(current)
        if current.phase == "tool_inflight":
            return SegmentResult(
                checkpoint=_replace(
                    current,
                    phase="outcome_unknown",
                    reason="Effect intent has no recorded receipt",
                )
            )
        if current.phase == "model_pending":
            current = self._model(current)
            if current.phase in TERMINAL_PHASES or stop_at == "after_model":
                return SegmentResult(checkpoint=current)
        if current.phase in {"tool_ready", "awaiting_approval"}:
            current = self._tool(current, approval, context, stop_at)
            if current.phase != "verifying" or stop_at == "after_receipt":
                return SegmentResult(checkpoint=current)
        return SegmentResult(checkpoint=self._verify(current))

    def _next_segment(self, checkpoint: WorkerCheckpoint) -> WorkerCheckpoint:
        number = checkpoint.segment_number + 1
        return _replace(
            checkpoint,
            segment_number=number,
            segment_id=str(segment_identity(checkpoint.binding.run_id, number)),
        )

    def _model(self, checkpoint: WorkerCheckpoint) -> WorkerCheckpoint:
        try:
            counters = consume_attempt(checkpoint.counters, self.scenario.limits, "model_requests")
        except ValueError as exc:
            return _replace(checkpoint, phase="limit_reached", reason=str(exc))
        if self.scenario.model_fails:
            return _replace(
                checkpoint,
                counters=counters.model_dump(mode="json"),
                phase="failed",
                reason="Synthetic model failure",
            )
        return _replace(
            checkpoint,
            counters=counters.model_dump(mode="json"),
            generated_output=self.scenario.model_output,
            phase="tool_ready",
        )

    def _tool(
        self,
        checkpoint: WorkerCheckpoint,
        approval: ApprovalDecision | None,
        context: ApprovalContext | None,
        stop_at: StopAt | None,
    ) -> WorkerCheckpoint:
        if self.scenario.requires_approval:
            if approval is None:
                return _replace(checkpoint, phase="awaiting_approval")
            if context is None:
                raise ValueError("Approval requires trusted current context")
            require_exact_approval(self.scenario.action, approval, context)
        try:
            counters = consume_attempt(checkpoint.counters, self.scenario.limits, "tool_attempts")
        except ValueError as exc:
            return _replace(checkpoint, phase="limit_reached", reason=str(exc))
        intent = _replace(
            checkpoint,
            phase="tool_inflight",
            counters=counters.model_dump(mode="json"),
            approval_decision_id=str(approval.decision_id) if approval is not None else None,
        )
        if stop_at == "after_tool_intent":
            return intent
        return self._record_receipt(intent)

    def _record_receipt(self, checkpoint: WorkerCheckpoint) -> WorkerCheckpoint:
        binding = checkpoint.binding
        receipt = ActionReceipt(
            company_id=binding.company_id,
            receipt_id=uuid5(binding.action_id, "nexus-fake-receipt-v1"),
            action_id=binding.action_id,
            task_id=binding.task_id,
            trace_id=binding.trace_id,
            proposal_hash=binding.action_hash,
            outcome=self.scenario.tool_outcome,
            recorded_at=self.scenario.recorded_at,
        )
        phase = {
            "succeeded": "verifying",
            "failed": "failed",
            "outcome_unknown": "outcome_unknown",
        }[self.scenario.tool_outcome]
        return _replace(checkpoint, phase=phase, receipt=receipt.model_dump(mode="json"))

    def _verify(self, checkpoint: WorkerCheckpoint) -> WorkerCheckpoint:
        verification = self.scenario.verification
        phase = {"pass": "completed", "reject": "failed", "inconclusive": "inconclusive"}[
            verification.verdict
        ]
        return _replace(
            checkpoint,
            verification=verification.model_dump(mode="json"),
            phase=phase,
        )
