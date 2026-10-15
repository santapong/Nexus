"""All issued candidates are counted before any state or receipt can select a winner."""

from unittest.mock import MagicMock
from uuid import UUID

import pytest

from nexus.tests.unit.cycle_prerequisite_fixture import NOW, deliverable_case, issued_case


@pytest.mark.parametrize("count", [0, 2, 3])
async def test_missing_or_multiple_native_identities_never_load_a_receipt(
    monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    from nexus.company.cycle_artifacts.engineering_prerequisite_facts import unique_issued_action

    case = deliverable_case(monkeypatch)
    result = MagicMock()
    result.all.return_value = [UUID(int=900 + value) for value in range(count)]
    case.session.scalars.return_value = result
    case.session.scalars.side_effect = None
    with pytest.raises(ValueError):
        await unique_issued_action(case.session, case.executions[3])
    statement = case.session.scalars.await_args.args[0]
    assert "succeeded" not in str(statement) and "state" not in str(statement)
    case.session.get.assert_not_awaited()


async def test_unique_identity_is_only_a_selector_not_a_passing_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.cycle_artifacts.engineering_prerequisite_facts import unique_issued_action

    case = deliverable_case(monkeypatch)
    result = MagicMock()
    result.all.return_value = [UUID(int=901)]
    case.session.scalars.return_value, case.session.scalars.side_effect = result, None
    assert await unique_issued_action(case.session, case.executions[3]) == UUID(int=901)
    case.session.get.assert_not_awaited()


async def test_actual_serialized_spec_receipt_attempt_and_original_fence() -> None:
    from nexus.company.cycle_artifacts.engineering_prerequisite_facts import _issued

    case = issued_case()
    spec, receipt, original = await _issued(case.session, case.work, case.action.id)
    assert spec.job.action_id == case.action.id and receipt == case.receipt
    assert original.original_fence == 1 < case.work.fence
    assert (
        original.consumed_at <= original.reserved_at <= original.created_at <= receipt.recorded_at
    )
    case.session.add.assert_not_called()


async def test_an_extra_graph_evidence_edge_is_not_silently_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock
    from uuid import uuid5

    from nexus.company.brain.base import BrainReadScope
    from nexus.company.brain.derivation_models import BrainDerivation
    from nexus.company.brain.source_models import BrainArtifactRevision
    from nexus.company.cycle_artifacts.engineering_prerequisite_facts import (
        require_engineering_graph_locked,
    )
    from nexus.tests.unit.engineering_body_fixture import described_body

    case = deliverable_case(monkeypatch)
    ref = described_body(b"x").first.artifact
    derivation = uuid5(ref.artifact_id, "derivation-v1")
    artifact = BrainArtifactRevision(
        company_id=ref.company_id,
        artifact_id=ref.artifact_id,
        artifact_revision_id=ref.artifact_revision_id,
        revision=ref.revision,
        sha256=ref.sha256,
        byte_length=ref.byte_length,
        raw_text="x",
        derivation_id=derivation,
        recorded_at=NOW,
    )
    native = BrainDerivation(company_id=ref.company_id, derivation_id=derivation, recorded_at=NOW)

    async def get(model: type[object], key: object) -> object:
        return artifact if model is BrainArtifactRevision else native

    case.session.get = AsyncMock(side_effect=get)
    result = MagicMock()
    result.all.return_value = [UUID(int=999)]
    case.session.scalars = AsyncMock(return_value=result)
    scope = BrainReadScope(
        company_id=ref.company_id,
        workspace_id=case.work.workspace_id,
        principal_id=case.work.actor_id,
        operation_id=UUID(int=997),
        trace_id=case.work.trace_id,
    )
    with pytest.raises(ValueError):
        await require_engineering_graph_locked(
            case.session, scope, ref, (ref,), recipe="native-builder-result-v1"
        )
    case.session.execute.assert_not_awaited()
    case.session.add.assert_not_called()
    case.session.flush.assert_not_called()


@pytest.mark.parametrize(
    "kind",
    [
        "unknown",
        "failed",
        "attempt",
        "fence",
        "boolean",
        "chronology",
        "consumed",
        "resource",
        "actor",
        "receipt",
        "counter",
    ],
)
async def test_native_facts_fail_closed_before_any_body_read(kind: str) -> None:
    from datetime import timedelta

    from nexus.company.contracts.actions import ActionProposal
    from nexus.company.cycle_artifacts.engineering_prerequisite_facts import _issued
    from nexus.harness.canonical import action_hash

    case = issued_case()
    if kind in {"unknown", "failed"}:
        case.effect.state = "outcome_unknown" if kind == "unknown" else "failed"
    elif kind == "attempt":
        case.attempt.kind = "model_requests"
    elif kind == "fence":
        case.effect.intent_fence = case.work.fence + 1
    elif kind == "boolean":
        case.effect.intent_fence = True
    elif kind == "chronology":
        case.attempt.reserved_at = NOW + timedelta(seconds=1)
    elif kind == "consumed":
        case.action.consumed_at = None
    elif kind == "counter":
        case.work.tool_attempts_used = 0
    elif kind in {"resource", "actor"}:
        action = ActionProposal.model_validate_json(case.action.proposal_json)
        action = action.model_copy(
            update={"resource": "different.resource"}
            if kind == "resource"
            else {"actor_id": UUID(int=999)}
        )
        case.action.proposal_json, case.action.proposal_hash = (
            action.model_dump_json(),
            action_hash(action),
        )
        case.effect.proposal_hash = action_hash(action)
    else:
        case.effect.receipt_json = case.receipt.model_copy(
            update={"outcome": "failed"}
        ).model_dump_json()
    with pytest.raises(ValueError):
        await _issued(case.session, case.work, case.action.id)
    case.session.execute.assert_not_awaited()
    case.session.add.assert_not_called()
