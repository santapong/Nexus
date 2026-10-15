"""Current C result orchestration and final-window retention; SQL/receipt gates remain separate."""

import json

import pytest

from nexus.company.strategy.artifact_identity import strategy_reference
from nexus.company.strategy.check_output import prepare_strategy_check
from nexus.company.strategy.result_reader import protect_strategy_check_result_locked
from nexus.tests.unit.strategy_result_reader_fixture import ResultCase, result_case


async def protect(case: ResultCase) -> None:
    reference = strategy_reference(
        prepare_strategy_check(case.material.command, case.material.inputs, "internal"),
        case.verifier_action_id,
    )
    await protect_strategy_check_result_locked(
        case.reader,
        case.flow.session,
        case.flow.source.control,
        case.lease,
        case.credential.identity,
        case.material,
        case.verifier_action_id,
        reference,
        credential=case.credential,
    )


async def test_current_result_rechecks_full_native_graph_and_preserves_original_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = result_case(monkeypatch)
    await protect(case)
    case.graph.assert_awaited_once()
    call = case.graph.await_args
    assert call is not None
    prepared = call.args[3]
    assert prepared.inputs == case.material.inputs
    assert len(prepared.inputs.artifacts) == len(case.flow.source.original.inputs.artifacts) + 2
    assert case.flow.prepared.compiled.prepared.inputs == case.flow.source.original.inputs


@pytest.mark.parametrize("change", ["bytes", "input_hash", "target_hash", "resource"])
async def test_current_c_body_and_complete_action_pins_cannot_be_spliced(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    case = result_case(monkeypatch)
    if change == "bytes":
        case.row.raw_text = "changed"
    elif change == "resource":
        case.row.resource_id = case.material.inputs.required_resource_ids[0]
    else:
        proposal = json.loads(case.record.proposal_json)
        field = "input_snapshot_sha256" if change == "input_hash" else "verification_target_sha256"
        proposal["parameters"][field] = "0" * 64
        from nexus.company.contracts.actions import ActionProposal
        from nexus.harness.canonical import action_hash

        action = ActionProposal.model_validate_json(json.dumps(proposal))
        case.record.proposal_json = action.model_dump_json()
        case.record.proposal_hash = action_hash(action)
    with pytest.raises(ValueError):
        await protect(case)


async def test_result_graph_await_cannot_drop_initial_recipient_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = result_case(monkeypatch)
    deadline = case.material.protection.grants[0].expires_at
    assert deadline is not None

    async def graph(*_: object) -> None:
        case.flow.source.clock["now"] = deadline

    case.graph.side_effect = graph
    with pytest.raises(ValueError):
        await protect(case)
    assert case.current.protection.grants == ()
