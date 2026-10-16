"""Native history delivery is supplied; orchestration must never retry an issued SDK action."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from nexus.builder.contained_query import clock_us
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.planning_history import NativePlanningHistory
from nexus.execution.planning_worker import execute_planning_segment
from nexus.execution.runtime_contracts import EffectRecord
from nexus.tests.unit.test_planning_services import services


def command() -> SegmentCommand:
    return SegmentCommand(
        company_id=UUID(int=1),
        task_id=UUID(int=6),
        trace_id=UUID(int=7),
        actor_id=UUID(int=3),
        workspace_id=UUID(int=2),
        run_id=UUID(int=8),
        action_id=UUID(int=5),
        segment_id=UUID(int=9),
    )


@pytest.mark.parametrize("state", ["succeeded", "failed", "intent", "outcome_unknown"])
async def test_issued_native_history_never_needs_fresh_credential_body_or_sdk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    from nexus.execution import planning_worker as module

    configured, selected = services(tmp_path), command()
    # Supplied native metadata, not independently validated SQL or billing proof.
    effect = EffectRecord.model_validate(
        {
            "company_id": selected.company_id,
            "action_id": selected.action_id,
            "task_id": selected.task_id,
            "trace_id": selected.trace_id,
            "run_id": selected.run_id,
            "proposal_hash": "a" * 64,
            "intent_fence": 1,
            "attempt_kind": "model_requests",
            "state": state,
            "created_at": datetime.now(UTC),
            "receipt": None,
            "verification": None,
        }
    )
    history = NativePlanningHistory(effect, "b" * 64)
    monkeypatch.setattr(module, "native_history", AsyncMock(return_value=history))
    credential = AsyncMock(side_effect=AssertionError("Historical metadata cannot refresh JWT"))
    load = AsyncMock(side_effect=AssertionError("Historical metadata cannot read private prompt"))
    claim = AsyncMock(side_effect=AssertionError("Historical metadata cannot reacquire a lease"))
    monkeypatch.setattr(type(configured.identities), "current", credential)
    monkeypatch.setattr(configured.prepared, "load_worker", load)
    monkeypatch.setattr(configured.execution, "recover_dispatched", claim)
    result = await execute_planning_segment(
        configured, selected, workflow_id=selected.workflow_id, end_us=clock_us() + 10_000_000
    )
    assert result.replayed and result.native_state == state
    assert result.status == (
        "known_history" if state in {"succeeded", "failed"} else "outcome_unknown"
    )
    assert not result.company_completed and result.resources_pending is False
    assert result.receipt_id is None  # Supplied history deliberately omitted receipts.
    credential.assert_not_awaited()
    load.assert_not_awaited()
    claim.assert_not_awaited()


async def test_foreign_workflow_cannot_read_or_start_a_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.execution import planning_worker as module

    configured, selected = services(tmp_path), command()
    history = AsyncMock()
    monkeypatch.setattr(module, "native_history", history)
    with pytest.raises(ValueError, match="workflow"):
        await execute_planning_segment(
            configured, selected, workflow_id="foreign", end_us=clock_us() + 10_000_000
        )
    history.assert_not_awaited()


@pytest.mark.parametrize("recorded_failure", [False, True])
async def test_cancelled_projection_retains_actual_governed_metadata_without_candidate(
    tmp_path: Path,
    recorded_failure: bool,
) -> None:
    from decimal import Decimal
    from uuid import uuid5

    from nexus.company.contracts.knowledge import ArtifactRef
    from nexus.core.llm.company_adapter_contracts import CompanyModelResult
    from nexus.core.llm.company_pricing import TokenUsage
    from nexus.execution.planning_services import PlanningOperation
    from nexus.execution.planning_worker import _result
    from nexus.harness.model_authorizer import RecordedModelOutcome
    from nexus.harness.model_client import GovernedModelClient
    from nexus.harness.model_client_contracts import GovernedModelCancelledError

    configured, selected = services(tmp_path), command()
    operation = PlanningOperation(configured, selected.workflow_id, clock_us() + 10_000_000)
    result = CompanyModelResult(
        request_id=selected.action_id,
        status="cancelled",
        billing="known" if recorded_failure else "unknown",
        usage=TokenUsage(input_tokens=100, output_tokens=20) if recorded_failure else None,
        error_code="cancelled",
    )
    artifact = ArtifactRef(
        company_id=selected.company_id,
        artifact_id=UUID(int=77),
        reference="/protected/not-read/provider-envelope.json",
        sha256="c" * 64,
        revision="model-result-envelope-v1",
        allowed_principals=(selected.actor_id, UUID(int=99)),
    )
    record = (
        RecordedModelOutcome(
            artifact=artifact,
            billing="known",
            actual_usd=Decimal("0.000360"),
            stop_required=True,
            receipt_id=uuid5(selected.action_id, "model-receipt-v1"),
        )
        if recorded_failure
        else None
    )
    governed = GovernedModelClient._outcome(
        result,
        record,
        recording_error=None if recorded_failure else "recording_timeout",
        release_error="release_failed",
    )
    original = GovernedModelCancelledError(governed)
    operation.first = original
    described = _result(
        selected, operation, NativePlanningHistory(None, "b" * 64), None, replayed=False
    )
    assert described.status == "outcome_unknown"
    assert described.native_state == ("failed" if recorded_failure else None)
    assert described.receipt_id == (record.receipt_id if record else None)
    assert described.artifact_sha256 == (artifact.sha256 if record else None)
    assert described.error_type == "GovernedModelCancelledError" and not described.company_completed
    assert "/protected/" not in described.model_dump_json()
    assert operation.first is original and original.governed.recorded == record
    operation.finish()
