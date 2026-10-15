"""Pure selector decoding; no native identity, permission or effect qualification."""

import json
from uuid import UUID

import pytest

from nexus.company.contracts.actions import ActionProposal
from nexus.company.cycle_artifacts.action_parameters import decode_cycle_action
from nexus.company.strategy.artifact_contracts import (
    StrategyBriefSelector,
    StrategyCheckParameters,
    StrategyWriteParameters,
)
from nexus.harness.standing_contracts import ToolPermission
from nexus.tests.unit.strategy_brief_fixture import strategy_case


def legacy_action() -> tuple[ActionProposal, ToolPermission]:
    case = strategy_case()
    scope = case.brief.scope
    params = StrategyWriteParameters(
        selector=StrategyBriefSelector(scope=scope),
        output_sha256=case.command.output.sha256,
        input_snapshot_sha256=case.brief.input_snapshot_sha256,
        input_manifest_sha256=case.brief.input_manifest_sha256,
    )
    action = ActionProposal(
        company_id=scope.company_id,
        action_id=UUID(int=880),
        actor_id=scope.author.actor_id,
        task_id=scope.author.task_id,
        trace_id=scope.author.trace_id,
        revision=1,
        tool="company.cycle-artifact.write.v1",
        tool_version="v1",
        resource="cycle.output",
        parameters=params.model_dump(mode="json"),
        estimated_cost_usd="0.01",
        policy_version="fixture",
        price_version="fixture",
    )
    return action, ToolPermission(tool=action.tool, tool_version="v1", resource=action.resource)


def decode(action: ActionProposal, permission: ToolPermission, kind: str = "strategy") -> object:
    return decode_cycle_action(
        action,
        expected_kind=kind,
        phase="write",
        binding=strategy_case().brief.scope.author,
        permission=permission,
    )


def test_exact_legacy_strategy_wire_is_returned_as_unchanged_original_parameter_type() -> None:
    action, permission = legacy_action()
    expected = StrategyWriteParameters.model_validate_json(json.dumps(action.parameters))
    actual = decode(action, permission)
    assert type(actual) is StrategyWriteParameters
    assert actual.model_dump_json() == expected.model_dump_json()


@pytest.mark.parametrize("kind", ["presentation", "support", "report", "", None])
def test_untagged_legacy_parameters_cannot_fall_back_from_another_expected_kind(kind: str) -> None:
    action, permission = legacy_action()
    with pytest.raises(ValueError):
        decode(action, permission, kind)


@pytest.mark.parametrize(
    "key,value", [("artifact_kind", "presentation"), ("report_id", str(UUID(int=9)))]
)
def test_legacy_strategy_does_not_gain_new_kind_or_report_selector_fields(
    key: str, value: str
) -> None:
    action, permission = legacy_action()
    action = action.model_copy(update={"parameters": {**action.parameters, key: value}})
    with pytest.raises(ValueError):
        decode(action, permission)


@pytest.mark.parametrize(
    "field,value", [("actor_id", UUID(int=9)), ("resource", "other.output"), ("tool_version", "v2")]
)
def test_selector_data_cannot_cross_trusted_role_tool_or_resource_binding(
    field: str, value: object
) -> None:
    action, permission = legacy_action()
    with pytest.raises(ValueError):
        decode(action.model_copy(update={field: value}), permission)


def test_legacy_strategy_check_wire_and_self_check_denial_remain_closed() -> None:
    original, _ = legacy_action()
    basis = strategy_case()
    params = StrategyCheckParameters(
        author_action_id=original.action_id,
        verification_target_sha256="c" * 64,
        output_sha256="d" * 64,
        input_snapshot_sha256="e" * 64,
    )
    binding = basis.brief.scope.verifier
    proposed = original.model_copy(
        update={
            "action_id": UUID(int=881),
            "actor_id": binding.actor_id,
            "task_id": binding.task_id,
            "trace_id": binding.trace_id,
            "tool": "company.cycle-artifact.check.v1",
            "parameters": params.model_dump(mode="json"),
        }
    )
    permission = ToolPermission(tool=proposed.tool, tool_version="v1", resource=proposed.resource)
    actual = decode_cycle_action(
        proposed, expected_kind="strategy", phase="check", binding=binding, permission=permission
    )
    assert (
        type(actual) is StrategyCheckParameters
        and actual.model_dump_json() == params.model_dump_json()
    )
    changed = proposed.model_copy(
        update={"parameters": {**proposed.parameters, "author_action_id": str(proposed.action_id)}}
    )
    with pytest.raises(ValueError):
        decode_cycle_action(
            changed, expected_kind="strategy", phase="check", binding=binding, permission=permission
        )
