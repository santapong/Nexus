"""Stable strategy artifact names and exact action pins; no publication or replay authority."""

import json
from uuid import UUID, uuid5

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.strategy.artifact_contracts import (
    PreparedStrategyArtifact,
    StrategyArtifactRule,
    StrategyCheckParameters,
    StrategyWriteParameters,
)


def strategy_artifact_id(company_id: UUID, action_id: UUID) -> UUID:
    return uuid5(company_id, f"management.strategy-artifact:{action_id}")


def strategy_derivation_id(company_id: UUID, action_id: UUID) -> UUID:
    return uuid5(strategy_artifact_id(company_id, action_id), "derivation:v1")


def strategy_reference(prepared: PreparedStrategyArtifact, action_id: UUID) -> ArtifactRevisionRef:
    prepared = PreparedStrategyArtifact.model_validate_json(prepared.model_dump_json())
    artifact_id = strategy_artifact_id(prepared.company_id, action_id)
    revision_id = uuid5(artifact_id, "revision:v1")
    if any(
        row.artifact_id == artifact_id or row.artifact_revision_id == revision_id
        for row in prepared.inputs.artifacts
    ):
        raise ValueError("Strategy artifact cannot be its own input")
    return ArtifactRevisionRef(
        company_id=prepared.company_id,
        artifact_id=artifact_id,
        artifact_revision_id=revision_id,
        revision="strategy-v1",
        sha256=prepared.output_sha256,
        byte_length=len(prepared.raw_bytes),
    )


def require_strategy_action_payload(
    actual_action: ActionProposal,
    rule: StrategyArtifactRule,
    prepared: PreparedStrategyArtifact,
) -> StrategyWriteParameters | StrategyCheckParameters:
    """Compare descriptions only; the publisher must resolve actual scope, intent and bytes."""
    actual_action = ActionProposal.model_validate_json(actual_action.model_dump_json())
    rule = StrategyArtifactRule.model_validate_json(rule.model_dump_json())
    prepared = PreparedStrategyArtifact.model_validate_json(prepared.model_dump_json())
    raw = json.dumps(actual_action.parameters, allow_nan=False)
    parameters: StrategyWriteParameters | StrategyCheckParameters
    if rule.tool == "company.cycle-artifact.write.v1":
        parameters = StrategyWriteParameters.model_validate_json(raw)
        author = parameters.selector.scope.author
        if (
            parameters.selector.scope.company_id != prepared.company_id
            or (actual_action.actor_id, actual_action.task_id, actual_action.trace_id)
            != (author.actor_id, author.task_id, author.trace_id)
            or parameters.input_manifest_sha256 != prepared.input_manifest_sha256
        ):
            raise ValueError("Strategy write selector or manifest differs from exact action")
    else:
        parameters = StrategyCheckParameters.model_validate_json(raw)
        if parameters.author_action_id == actual_action.action_id:
            raise ValueError("Strategy verifier cannot select its own action")
    if (
        actual_action.company_id != prepared.company_id
        or rule.company_id != prepared.company_id
        or (actual_action.tool, actual_action.tool_version, actual_action.resource)
        != (rule.tool, rule.tool_version, rule.resource_symbol)
        or parameters.recipe_version != prepared.recipe_version
        or parameters.output_sha256 != prepared.output_sha256
        or parameters.input_snapshot_sha256 != prepared.input_snapshot_sha256
    ):
        raise ValueError("Strategy bytes differ from fixed exact action pins")
    return parameters
