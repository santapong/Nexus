"""Stable action identities and fixed declaration pins; no DB authority or publication permit."""

import json
from uuid import UUID, uuid5

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.generated_artifact_contracts import (
    GeneratedArtifactActionParameters,
    GeneratedArtifactPayload,
    GeneratedArtifactRule,
)


def generated_artifact_id(company_id: UUID, action_id: UUID) -> UUID:
    """One company/action artifact identity cannot evade immutable bytes by changing hashes."""
    return uuid5(company_id, f"management.generated-artifact:{action_id}")


def generated_derivation_id(company_id: UUID, action_id: UUID) -> UUID:
    """Stable provenance identity is distinct from artifact revision and contains no authority."""
    return uuid5(generated_artifact_id(company_id, action_id), "derivation:v1")


def generated_reference(prepared: GeneratedArtifactPayload, action_id: UUID) -> ArtifactRevisionRef:
    """Name an exact pending revision, including changed-byte conflict and self-input detection."""
    prepared = GeneratedArtifactPayload.model_validate_json(prepared.model_dump_json())
    artifact_id = generated_artifact_id(prepared.company_id, action_id)
    revision_id = uuid5(artifact_id, "revision:v1")
    if any(
        row.artifact_id == artifact_id or row.artifact_revision_id == revision_id
        for row in prepared.inputs.artifacts
    ):
        raise ValueError("Generated artifact cannot be its own input")
    return ArtifactRevisionRef(
        company_id=prepared.company_id,
        artifact_id=artifact_id,
        artifact_revision_id=revision_id,
        revision="generated-v1",
        sha256=prepared.output_sha256,
        byte_length=len(prepared.raw_bytes),
    )


def require_action_payload(
    actual_action: ActionProposal, rule: GeneratedArtifactRule, prepared: GeneratedArtifactPayload
) -> GeneratedArtifactActionParameters:
    """Structural pins supplement actual current native action/lease/provenance gates."""
    rule = GeneratedArtifactRule.model_validate_json(rule.model_dump_json())
    actual_action = ActionProposal.model_validate_json(actual_action.model_dump_json())
    prepared = GeneratedArtifactPayload.model_validate_json(prepared.model_dump_json())
    parameters = GeneratedArtifactActionParameters.model_validate_json(
        json.dumps(actual_action.parameters, allow_nan=False)
    )
    if (
        actual_action.company_id != prepared.company_id
        or rule.company_id != prepared.company_id
        or actual_action.tool != rule.tool
        or actual_action.tool_version != rule.tool_version
        or actual_action.resource != rule.resource_symbol
        or parameters.recipe_version != prepared.recipe_version
        or rule.recipe_version != prepared.recipe_version
        or parameters.output_sha256 != prepared.output_sha256
        or parameters.input_snapshot_sha256 != prepared.input_snapshot_sha256
        or (rule.tool == "company.report.write.v1" and parameters.report_id is None)
        or (
            rule.tool == "company.report.check.v1" and parameters.verification_target_sha256 is None
        )
    ):
        raise ValueError("Generated payload differs from fixed exact native action pins")
    return parameters
