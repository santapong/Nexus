"""Deterministic checkpoint serialization and trusted replay boundary checks."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid5

from pydantic import BaseModel

from nexus.execution.contracts import (
    CheckpointCounters,
    CheckpointEnvelope,
    FakeScenario,
    WorkerBinding,
    WorkerCheckpoint,
)
from nexus.harness.canonical import action_hash
from nexus.harness.limits import LoopCounters


def _digest(value: BaseModel) -> str:
    payload = json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def worker_binding(scenario: FakeScenario, *, run_id: UUID) -> WorkerBinding:
    """Bind a replay to the exact work, proposal, fixture and implementation version."""
    return WorkerBinding(
        company_id=scenario.work.company_id,
        task_id=scenario.work.task_id,
        trace_id=scenario.work.trace_id,
        run_id=run_id,
        action_id=scenario.action.action_id,
        workflow_version=scenario.workflow_version,
        model_version=scenario.model_version,
        work_hash=_digest(scenario.work),
        action_hash=action_hash(scenario.action),
        scenario_hash=_digest(scenario),
    )


def segment_identity(run_id: UUID, segment_number: int) -> UUID:
    """Derive reproducible segment identities while retaining one logical run ID."""
    return uuid5(run_id, f"nexus-worker-segment-v1:{segment_number}")


def start_checkpoint(scenario: FakeScenario, *, run_id: UUID) -> WorkerCheckpoint:
    """Create explicit zero counters only for a new trusted logical run."""
    return WorkerCheckpoint(
        binding=worker_binding(scenario, run_id=run_id),
        phase="model_pending",
        counters=CheckpointCounters.model_validate(LoopCounters().model_dump()),
        segment_number=0,
        segment_id=segment_identity(run_id, 0),
        generated_output=None,
        approval_decision_id=None,
        receipt=None,
        verification=None,
        reason=None,
    )


def validate_replay(
    checkpoint: WorkerCheckpoint,
    *,
    scenario: FakeScenario,
    expected_run_id: UUID,
    minimum_counters: LoopCounters,
) -> WorkerCheckpoint:
    """Revalidate trusted data, content binding and independently retained counters.

    The caller must obtain minimum counters/run identity from authoritative state.
    Copying them from untrusted input would defeat rollback detection. This pure
    check neither locks concurrent workers nor proves persistence/crash recovery.
    """
    checked = WorkerCheckpoint.model_validate_json(checkpoint.model_dump_json())
    if checked.binding != worker_binding(scenario, run_id=expected_run_id):
        raise ValueError("Checkpoint binding differs from expected work/run/version")
    if checked.segment_id != segment_identity(expected_run_id, checked.segment_number):
        raise ValueError("Checkpoint segment identity differs from binding")
    for kind in LoopCounters.model_fields:
        used = getattr(checked.counters, kind)
        if used < getattr(minimum_counters, kind) or used > getattr(scenario.limits, kind):
            raise ValueError(f"Checkpoint counter violates floor or limit: {kind}")
    if checked.generated_output not in {None, scenario.model_output}:
        raise ValueError("Checkpoint output differs from bound fake model")
    if checked.verification is not None and checked.verification != scenario.verification:
        raise ValueError("Checkpoint verification differs from bound fixture")
    if checked.receipt is not None and (
        checked.receipt.outcome != scenario.tool_outcome
        or checked.receipt.recorded_at != scenario.recorded_at
        or checked.receipt.receipt_id != uuid5(scenario.action.action_id, "nexus-fake-receipt-v1")
        or checked.receipt.external_id is not None
        or checked.receipt.artifacts
    ):
        raise ValueError("Checkpoint receipt differs from bound fake tool")
    return checked


def dump_checkpoint(checkpoint: WorkerCheckpoint) -> str:
    """Produce JSON only; clients, sessions and executable objects cannot be stored."""
    checked = WorkerCheckpoint.model_validate_json(checkpoint.model_dump_json())
    return CheckpointEnvelope(checksum=_digest(checked), checkpoint=checked).model_dump_json()


def load_checkpoint(
    serialized: str,
    *,
    scenario: FakeScenario,
    expected_run_id: UUID,
    minimum_counters: LoopCounters,
) -> WorkerCheckpoint:
    """Reject malformed/stale/corrupt snapshots without recreating missing counters."""
    envelope = CheckpointEnvelope.model_validate_json(serialized)
    if envelope.checksum != _digest(envelope.checkpoint):
        raise ValueError("Checkpoint checksum mismatch")
    return validate_replay(
        envelope.checkpoint,
        scenario=scenario,
        expected_run_id=expected_run_id,
        minimum_counters=minimum_counters,
    )
