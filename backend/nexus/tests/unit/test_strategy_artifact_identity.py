"""Pure strategy action pins; synthetic descriptions never exercise publication authority."""

import hashlib
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.generated_artifact_identity import generated_artifact_id
from nexus.company.strategy.artifact_contracts import (
    PreparedStrategyArtifact,
    StrategyArtifactRule,
    StrategyBriefSelector,
    StrategyCheckParameters,
    StrategyWriteParameters,
)
from nexus.company.strategy.artifact_identity import (
    require_strategy_action_payload,
    strategy_artifact_id,
    strategy_derivation_id,
    strategy_reference,
)
from nexus.tests.unit.strategy_brief_fixture import strategy_case


def _prepared() -> PreparedStrategyArtifact:
    case = strategy_case()
    assert case.command.snapshot is not None
    raw = case.brief.model_dump_json().encode()
    return PreparedStrategyArtifact(
        company_id=case.command.company_id,
        raw_bytes=raw,
        output_sha256=hashlib.sha256(raw).hexdigest(),
        input_snapshot_sha256=case.brief.input_snapshot_sha256,
        data_classification="internal",
        inputs=case.command.snapshot.inputs,
    )


def _rule(*, check: bool = False) -> StrategyArtifactRule:
    return StrategyArtifactRule(
        company_id=UUID(int=1),
        tool="company.cycle-artifact.check.v1" if check else "company.cycle-artifact.write.v1",
        resource_symbol="strategy.output",
        target=ResourceRef(company_id=UUID(int=1), resource_id=UUID(int=80)),
        source_policy="generated.strategy-check.v1" if check else "generated.strategy.v1",
    )


def _action(*, check: bool = False) -> ActionProposal:
    prepared = _prepared()
    scope = strategy_case().brief.scope
    parameters: StrategyWriteParameters | StrategyCheckParameters
    if check:
        parameters = StrategyCheckParameters(
            author_action_id=UUID(int=81),
            verification_target_sha256="d" * 64,
            output_sha256=prepared.output_sha256,
            input_snapshot_sha256=prepared.input_snapshot_sha256,
        )
    else:
        parameters = StrategyWriteParameters(
            selector=StrategyBriefSelector(scope=scope),
            output_sha256=prepared.output_sha256,
            input_snapshot_sha256=prepared.input_snapshot_sha256,
            input_manifest_sha256=prepared.input_manifest_sha256,
        )
    actor = scope.verifier if check else scope.author
    return ActionProposal(
        company_id=prepared.company_id,
        action_id=UUID(int=82),
        task_id=actor.task_id,
        trace_id=actor.trace_id,
        actor_id=actor.actor_id,
        revision=1,
        tool=_rule(check=check).tool,
        tool_version="v1",
        resource="strategy.output",
        parameters=parameters.model_dump(mode="json"),
        policy_version="synthetic-v1",
        price_version="synthetic-v1",
        estimated_cost_usd=Decimal(".01"),
    )


@pytest.mark.parametrize("check", [False, True])
def test_strategy_exact_action_parameters_round_trip(check: bool) -> None:
    result = require_strategy_action_payload(_action(check=check), _rule(check=check), _prepared())
    expected = StrategyCheckParameters if check else StrategyWriteParameters
    assert isinstance(result, expected)


def test_strategy_identity_is_stable_and_separate_from_report() -> None:
    value = _prepared()
    action_id = UUID(int=82)
    reference = strategy_reference(value, action_id)
    assert reference.artifact_id == strategy_artifact_id(value.company_id, action_id)
    changed = value.model_copy(
        update={"raw_bytes": b"{}", "output_sha256": hashlib.sha256(b"{}").hexdigest()}
    )
    other = strategy_reference(changed, action_id)
    assert reference.artifact_id == other.artifact_id
    assert reference.artifact_revision_id == other.artifact_revision_id
    assert (
        reference.sha256 != other.sha256
    )  # A later store must reject conflicting immutable bytes.
    assert reference.artifact_id != generated_artifact_id(value.company_id, action_id)
    assert strategy_derivation_id(value.company_id, action_id) != reference.artifact_revision_id
    assert strategy_reference(value, UUID(int=83)).artifact_id != reference.artifact_id


@pytest.mark.parametrize(
    "field", ["tool", "tool_version", "resource", "company_id", "actor_id", "task_id", "trace_id"]
)
def test_strategy_write_rejects_wrong_action_scope(field: str) -> None:
    action = _action()
    replacement = UUID(int=999) if field.endswith("_id") else "wrong"
    with pytest.raises(ValueError):
        require_strategy_action_payload(
            action.model_copy(update={field: replacement}), _rule(), _prepared()
        )


@pytest.mark.parametrize(
    "field", ["output_sha256", "input_snapshot_sha256", "input_manifest_sha256"]
)
def test_strategy_write_rejects_changed_pin(field: str) -> None:
    action = _action()
    parameters = {**action.parameters, field: "f" * 64}
    with pytest.raises(ValueError):
        require_strategy_action_payload(
            action.model_copy(update={"parameters": parameters}), _rule(), _prepared()
        )


@pytest.mark.parametrize(
    "extra", [{"report_id": str(UUID(int=1))}, {"approved": True}, {"accepted": True}]
)
def test_strategy_parameters_reject_report_and_authority_aliases(extra: dict[str, object]) -> None:
    action = _action()
    with pytest.raises(ValueError):
        require_strategy_action_payload(
            action.model_copy(update={"parameters": {**action.parameters, **extra}}),
            _rule(),
            _prepared(),
        )


def test_strategy_check_cannot_select_its_own_action() -> None:
    action = _action(check=True)
    parameters = {**action.parameters, "author_action_id": str(action.action_id)}
    with pytest.raises(ValueError, match="own action"):
        require_strategy_action_payload(
            action.model_copy(update={"parameters": parameters}), _rule(check=True), _prepared()
        )


@pytest.mark.parametrize(
    "change",
    [
        {"source_policy": "generated.strategy-check.v1"},
        {"tool": "company.report.write.v1"},
        {"target": ResourceRef(company_id=UUID(int=99), resource_id=UUID(int=80))},
    ],
)
def test_strategy_rule_rejects_wrong_policy_tool_or_target(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        StrategyArtifactRule.model_validate(_rule().model_copy(update=change).model_dump())


@pytest.mark.parametrize(
    "change",
    [
        {"data_classification": "public"},
        {"output_sha256": "f" * 64},
        {"recipe_version": "report-v1"},
        {"raw_bytes": b"\xff"},
    ],
)
def test_strategy_prepared_requires_private_exact_utf8(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        strategy_reference(_prepared().model_copy(update=change), UUID(int=82))


def test_strategy_reference_rejects_its_own_input() -> None:
    value, action = _prepared(), UUID(int=82)
    reference = strategy_reference(value, action)
    inputs = value.inputs.model_copy(update={"artifacts": (*value.inputs.artifacts, reference)})
    with pytest.raises(ValueError, match="own input"):
        strategy_reference(value.model_copy(update={"inputs": inputs}), action)
