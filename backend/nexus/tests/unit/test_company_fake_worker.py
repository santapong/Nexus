"""Offline worker acceptance: replay is fail-closed and cannot manufacture success."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.contracts.actions import ApprovalDecision
from nexus.execution.checkpoint import dump_checkpoint, load_checkpoint, start_checkpoint
from nexus.execution.contracts import FakeScenario, WorkerCheckpoint
from nexus.execution.fake_worker import FakeWorker
from nexus.harness.approvals import ApprovalContext
from nexus.harness.canonical import action_hash
from nexus.harness.limits import LoopCounters

FIXTURE = Path(__file__).parents[1] / "fixtures/company_worker_v1/readiness.json"
RUN_ID = UUID(int=20)
NOW = datetime(2026, 10, 13, 10, tzinfo=UTC)
OWNER_ID = UUID(int=2)


@pytest.fixture
def scenario() -> FakeScenario:
    """Read one immutable synthetic scenario with no external dependencies."""
    return FakeScenario.model_validate_json(FIXTURE.read_text())


def approved(scenario: FakeScenario) -> ApprovalDecision:
    """Bind a current owner decision to exactly the simulated action."""
    return ApprovalDecision(
        company_id=scenario.work.company_id,
        decision_id=UUID(int=7),
        action_id=scenario.action.action_id,
        action_revision=scenario.action.revision,
        action_hash=action_hash(scenario.action),
        approver_id=OWNER_ID,
        decision="approved",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=24),
    )


def context(scenario: FakeScenario) -> ApprovalContext:
    """Use trusted current scope rather than trusting checkpoint authority."""
    return ApprovalContext(
        company_id=scenario.work.company_id,
        owner_id=OWNER_ID,
        actor_id=scenario.action.actor_id,
        now=NOW,
        policy_version=scenario.action.policy_version,
        price_version=scenario.action.price_version,
        paused=False,
        resources=scenario.action.preconditions,
    )


def restore(checkpoint: WorkerCheckpoint, scenario: FakeScenario) -> WorkerCheckpoint:
    """Restore with independently retained minimum counters and expected run identity."""
    return load_checkpoint(
        dump_checkpoint(checkpoint),
        scenario=scenario,
        expected_run_id=RUN_ID,
        minimum_counters=checkpoint.counters,
    )


def test_approval_wait_ends_segment_and_does_not_execute_tool(scenario: FakeScenario) -> None:
    result = FakeWorker(scenario).run_segment(start_checkpoint(scenario, run_id=RUN_ID))
    assert result.segment_released is True
    assert result.checkpoint.phase == "awaiting_approval"
    assert result.checkpoint.counters.model_requests == 1
    assert result.checkpoint.counters.tool_attempts == 0
    assert result.checkpoint.receipt is None
    assert result.checkpoint.verification is None
    assert result.checkpoint.generated_output == scenario.model_output


def test_resume_preserves_logical_ids_and_consumed_attempts(scenario: FakeScenario) -> None:
    worker = FakeWorker(scenario)
    waiting = worker.run_segment(start_checkpoint(scenario, run_id=RUN_ID)).checkpoint
    resumed = worker.run_segment(
        restore(waiting, scenario), approval=approved(scenario), context=context(scenario)
    ).checkpoint
    assert resumed.binding == waiting.binding
    assert resumed.segment_number == 2
    assert resumed.segment_id != waiting.segment_id
    assert resumed.phase == "completed"
    assert (
        resumed.counters.model_dump()
        == LoopCounters(model_requests=1, tool_attempts=1).model_dump()
    )
    assert resumed.verification is not None and resumed.verification.verdict == "pass"


def test_approval_polling_releases_slot_without_consuming_attempt(scenario: FakeScenario) -> None:
    worker = FakeWorker(scenario)
    waiting = worker.run_segment(start_checkpoint(scenario, run_id=RUN_ID)).checkpoint
    again = worker.run_segment(restore(waiting, scenario))
    assert again.segment_released and again.checkpoint == waiting


def test_generated_text_is_not_completed_work(scenario: FakeScenario) -> None:
    result = FakeWorker(scenario).run_segment(
        start_checkpoint(scenario, run_id=RUN_ID), stop_at="after_model"
    )
    assert result.checkpoint.phase == "tool_ready"
    assert result.checkpoint.receipt is None and result.checkpoint.verification is None


def test_lost_receipt_snapshot_fails_closed_without_repeating_effect(
    scenario: FakeScenario,
) -> None:
    worker = FakeWorker(scenario)
    intent = worker.run_segment(
        start_checkpoint(scenario, run_id=RUN_ID),
        approval=approved(scenario),
        context=context(scenario),
        stop_at="after_tool_intent",
    ).checkpoint
    assert intent.phase == "tool_inflight"
    restored = worker.run_segment(restore(intent, scenario)).checkpoint
    assert restored.phase == "outcome_unknown"
    assert restored.counters == intent.counters
    assert restored.receipt is None
    assert worker.run_segment(restore(restored, scenario)).checkpoint == restored


def test_recorded_receipt_verifies_without_retry(scenario: FakeScenario) -> None:
    worker = FakeWorker(scenario)
    recorded = worker.run_segment(
        start_checkpoint(scenario, run_id=RUN_ID),
        approval=approved(scenario),
        context=context(scenario),
        stop_at="after_receipt",
    ).checkpoint
    finished = worker.run_segment(restore(recorded, scenario)).checkpoint
    assert finished.phase == "completed"
    assert finished.receipt == recorded.receipt
    assert finished.counters == recorded.counters
    assert worker.run_segment(restore(finished, scenario)).checkpoint == finished


@pytest.mark.parametrize("verdict, phase", [("reject", "failed"), ("inconclusive", "inconclusive")])
def test_verification_never_promotes_reject_or_uncertainty(
    scenario: FakeScenario, verdict: str, phase: str
) -> None:
    payload = scenario.model_dump()
    payload["verification"]["verdict"] = verdict
    changed = FakeScenario.model_validate(payload)
    result = FakeWorker(changed).run_segment(
        start_checkpoint(changed, run_id=RUN_ID),
        approval=approved(changed),
        context=context(changed),
    )
    assert result.checkpoint.phase == phase


@pytest.mark.parametrize("field", ["workflow_version", "model_version"])
def test_changed_worker_or_model_version_cannot_resume(scenario: FakeScenario, field: str) -> None:
    waiting = FakeWorker(scenario).run_segment(start_checkpoint(scenario, run_id=RUN_ID)).checkpoint
    changed = FakeScenario.model_validate(scenario.model_dump() | {field: "changed-v2"})
    with pytest.raises(ValueError, match="binding"):
        restore(waiting, changed)


def test_changed_action_payload_cannot_resume(scenario: FakeScenario) -> None:
    waiting = FakeWorker(scenario).run_segment(start_checkpoint(scenario, run_id=RUN_ID)).checkpoint
    payload = scenario.model_dump()
    payload["action"]["parameters"]["text"] = "different draft"
    with pytest.raises(ValueError, match="binding"):
        restore(waiting, FakeScenario.model_validate(payload))


def test_changed_work_acceptance_cannot_resume(scenario: FakeScenario) -> None:
    waiting = FakeWorker(scenario).run_segment(start_checkpoint(scenario, run_id=RUN_ID)).checkpoint
    payload = scenario.model_dump()
    payload["work"]["acceptance"] = ("changed criterion",)
    payload["verification"]["criterion_ids"] = ("changed criterion",)
    with pytest.raises(ValueError, match="binding"):
        restore(waiting, FakeScenario.model_validate(payload))


def test_foreign_run_identity_cannot_restore(scenario: FakeScenario) -> None:
    checkpoint = start_checkpoint(scenario, run_id=RUN_ID)
    with pytest.raises(ValueError, match="binding"):
        load_checkpoint(
            dump_checkpoint(checkpoint),
            scenario=scenario,
            expected_run_id=UUID(int=999),
            minimum_counters=LoopCounters(),
        )


def test_checkpoint_checksum_rejects_corruption(scenario: FakeScenario) -> None:
    data = json.loads(dump_checkpoint(start_checkpoint(scenario, run_id=RUN_ID)))
    data["checkpoint"]["counters"]["model_requests"] = 1
    with pytest.raises(ValueError, match="checksum"):
        load_checkpoint(
            json.dumps(data),
            scenario=scenario,
            expected_run_id=RUN_ID,
            minimum_counters=LoopCounters(),
        )


@pytest.mark.parametrize("field", ["counters", "binding", "segment_number", "phase"])
def test_missing_checkpoint_state_is_rejected(scenario: FakeScenario, field: str) -> None:
    payload = start_checkpoint(scenario, run_id=RUN_ID).model_dump()
    del payload[field]
    with pytest.raises(ValidationError):
        WorkerCheckpoint.model_validate(payload)


def test_missing_individual_counter_is_rejected(scenario: FakeScenario) -> None:
    payload = start_checkpoint(scenario, run_id=RUN_ID).model_dump()
    del payload["counters"]["tool_attempts"]
    with pytest.raises(ValidationError):
        WorkerCheckpoint.model_validate(payload)


def test_counter_rollback_below_authoritative_floor_is_rejected(scenario: FakeScenario) -> None:
    checkpoint = start_checkpoint(scenario, run_id=RUN_ID)
    with pytest.raises(ValueError, match="counter"):
        load_checkpoint(
            dump_checkpoint(checkpoint),
            scenario=scenario,
            expected_run_id=RUN_ID,
            minimum_counters=LoopCounters(model_requests=1),
        )


@pytest.mark.parametrize("kind, amount", [("model_requests", 12), ("tool_attempts", 20)])
def test_exhausted_limits_do_not_reset_on_resume(
    scenario: FakeScenario, kind: str, amount: int
) -> None:
    checkpoint = start_checkpoint(scenario, run_id=RUN_ID)
    payload = checkpoint.model_dump()
    payload["counters"][kind] = amount
    checkpoint = WorkerCheckpoint.model_validate(payload)
    result = FakeWorker(scenario).run_segment(
        restore(checkpoint, scenario), approval=approved(scenario), context=context(scenario)
    )
    assert result.checkpoint.phase == "limit_reached"
    assert getattr(result.checkpoint.counters, kind) == amount


def test_model_failure_counts_the_attempt(scenario: FakeScenario) -> None:
    changed = FakeScenario.model_validate(scenario.model_dump() | {"model_fails": True})
    result = FakeWorker(changed).run_segment(start_checkpoint(changed, run_id=RUN_ID))
    assert result.checkpoint.phase == "failed"
    assert result.checkpoint.counters.model_requests == 1


@pytest.mark.parametrize(
    "outcome, phase", [("failed", "failed"), ("outcome_unknown", "outcome_unknown")]
)
def test_tool_failure_or_uncertainty_consumes_attempt_without_verified_success(
    scenario: FakeScenario, outcome: str, phase: str
) -> None:
    changed = FakeScenario.model_validate(scenario.model_dump() | {"tool_outcome": outcome})
    result = FakeWorker(changed).run_segment(
        start_checkpoint(changed, run_id=RUN_ID),
        approval=approved(changed),
        context=context(changed),
    )
    assert result.checkpoint.phase == phase
    assert result.checkpoint.counters.tool_attempts == 1
    assert result.checkpoint.verification is None


def test_stale_approval_cannot_consume_tool_attempt(scenario: FakeScenario) -> None:
    stale = ApprovalDecision.model_validate(
        approved(scenario).model_dump() | {"action_hash": "0" * 64}
    )
    with pytest.raises(ValueError, match="exact"):
        FakeWorker(scenario).run_segment(
            start_checkpoint(scenario, run_id=RUN_ID), approval=stale, context=context(scenario)
        )


def test_completed_checkpoint_without_verification_is_rejected(scenario: FakeScenario) -> None:
    payload = start_checkpoint(scenario, run_id=RUN_ID).model_dump() | {"phase": "completed"}
    with pytest.raises(ValidationError):
        WorkerCheckpoint.model_validate(payload)


def test_fixture_cannot_use_actor_as_independent_verifier(scenario: FakeScenario) -> None:
    payload = scenario.model_dump()
    payload["verification"]["verifier_id"] = scenario.action.actor_id
    with pytest.raises(ValidationError, match="independent"):
        FakeScenario.model_validate(payload)


@pytest.mark.parametrize("value", [True, "1", 1.5, None, -1])
def test_malformed_counter_cannot_be_coerced_to_progress(
    scenario: FakeScenario, value: object
) -> None:
    payload = start_checkpoint(scenario, run_id=RUN_ID).model_dump()
    payload["counters"]["tool_attempts"] = value
    with pytest.raises(ValidationError):
        WorkerCheckpoint.model_validate(payload)


def test_unknown_effect_without_a_tool_intent_is_rejected(scenario: FakeScenario) -> None:
    payload = start_checkpoint(scenario, run_id=RUN_ID).model_dump() | {"phase": "outcome_unknown"}
    with pytest.raises(ValidationError):
        WorkerCheckpoint.model_validate(payload)


def test_recorded_receipt_cannot_change_its_bound_fake_outcome(scenario: FakeScenario) -> None:
    worker = FakeWorker(scenario)
    recorded = worker.run_segment(
        start_checkpoint(scenario, run_id=RUN_ID),
        approval=approved(scenario),
        context=context(scenario),
        stop_at="after_receipt",
    ).checkpoint
    payload = recorded.model_dump()
    payload["receipt"]["recorded_at"] = NOW + timedelta(seconds=1)
    changed = WorkerCheckpoint.model_validate(payload)
    with pytest.raises(ValueError, match="receipt"):
        restore(changed, scenario)


def test_approval_without_current_authority_context_cannot_execute(scenario: FakeScenario) -> None:
    with pytest.raises(ValueError, match="context"):
        FakeWorker(scenario).run_segment(
            start_checkpoint(scenario, run_id=RUN_ID),
            approval=approved(scenario),
        )


def test_rework_and_plan_counts_are_preserved_across_segments(scenario: FakeScenario) -> None:
    payload = start_checkpoint(scenario, run_id=RUN_ID).model_dump()
    payload["counters"] |= {"rework_rounds": 1, "plan_revisions": 2}
    checkpoint = WorkerCheckpoint.model_validate(payload)
    worker = FakeWorker(scenario)
    waiting = worker.run_segment(restore(checkpoint, scenario)).checkpoint
    completed = worker.run_segment(
        restore(waiting, scenario), approval=approved(scenario), context=context(scenario)
    ).checkpoint
    assert completed.counters.rework_rounds == 1
    assert completed.counters.plan_revisions == 2


@pytest.mark.parametrize("field", ["company_id", "task_id", "trace_id"])
def test_foreign_action_scope_is_rejected(scenario: FakeScenario, field: str) -> None:
    payload = scenario.model_dump()
    payload["action"][field] = UUID(int=999)
    with pytest.raises(ValidationError, match="identities"):
        FakeScenario.model_validate(payload)


def test_non_fake_tool_is_rejected_before_execution(scenario: FakeScenario) -> None:
    payload = scenario.model_dump()
    payload["action"]["tool"] = "git.push"
    with pytest.raises(ValidationError, match="fake tools"):
        FakeScenario.model_validate(payload)


def test_altered_segment_identity_is_rejected(scenario: FakeScenario) -> None:
    payload = start_checkpoint(scenario, run_id=RUN_ID).model_dump()
    payload["segment_id"] = UUID(int=999)
    with pytest.raises(ValueError, match="segment identity"):
        restore(WorkerCheckpoint.model_validate(payload), scenario)


def test_foreign_receipt_cannot_be_recorded(scenario: FakeScenario) -> None:
    recorded = (
        FakeWorker(scenario)
        .run_segment(
            start_checkpoint(scenario, run_id=RUN_ID),
            approval=approved(scenario),
            context=context(scenario),
            stop_at="after_receipt",
        )
        .checkpoint
    )
    payload = recorded.model_dump()
    payload["receipt"]["action_id"] = UUID(int=999)
    with pytest.raises(ValidationError, match="Receipt"):
        WorkerCheckpoint.model_validate(payload)


def test_completed_receipt_without_model_output_is_invalid(scenario: FakeScenario) -> None:
    completed = (
        FakeWorker(scenario)
        .run_segment(
            start_checkpoint(scenario, run_id=RUN_ID),
            approval=approved(scenario),
            context=context(scenario),
        )
        .checkpoint
    )
    payload = completed.model_dump() | {"generated_output": None}
    with pytest.raises(ValidationError, match="Receipt"):
        WorkerCheckpoint.model_validate(payload)
