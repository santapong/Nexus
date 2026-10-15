"""Recomputed supplied-data exports and facts; a passing result grants no native authority."""

import json

from pydantic import ValidationError

from nexus.company.cycle_artifacts.check_contracts import (
    CycleArtifactCheckInput,
    CycleArtifactCheckPayload,
    CycleArtifactCheckResult,
    cycle_check_snapshot,
)
from nexus.company.cycle_artifacts.common import CycleDataError, bounded_json, criteria_for
from nexus.company.cycle_artifacts.contracts import checked_basis
from nexus.company.cycle_artifacts.payloads import PresentationBrief, SupportDraft
from nexus.company.cycle_artifacts.production import prepare_presentation, prepare_support
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import CheckVerdict, CriterionCheckResult


def check_cycle_artifact(command: CycleArtifactCheckInput) -> CycleArtifactCheckResult:
    command = CycleArtifactCheckInput.model_validate(command.model_dump(warnings=False))
    if (
        command.target.check_recipe != f"stockflow-{command.artifact_kind}-v1"
        or command.target.criterion_ids != criteria_for(command.artifact_kind)
    ):
        return _result(command, "inconclusive", "unsupported_or_incomplete_cycle_criteria")
    if command.original is None or command.typed_json is None or command.human_export is None:
        return _result(command, "inconclusive", "protected_cycle_inputs_unavailable")
    basis = checked_basis(command.original)
    if not _links(command):
        return _result(command, "reject", "cycle_target_input_or_original_binding_differs")
    try:
        bounded_json(command.typed_json)
        model = PresentationBrief if command.artifact_kind == "presentation" else SupportDraft
        body = model.model_validate_json(command.typed_json)
    except (CycleDataError, json.JSONDecodeError, UnicodeError, ValidationError, RecursionError):
        return _result(command, "reject", "cycle_data_malformed_or_unsupported_claim")
    if body.basis != basis:
        return _result(command, "reject", "cycle_original_basis_differs")
    prepare = prepare_presentation if command.artifact_kind == "presentation" else prepare_support
    expected = prepare(basis, command.target.action_id)
    if (
        expected.manifest != command.manifest
        or expected.typed_json != command.typed_json
        or expected.human_export != command.human_export
    ):
        return _result(command, "reject", "cycle_recomputed_bytes_or_export_manifest_differs")
    return _result(command, "pass", "exact_supported_cycle_draft_and_export")


def _links(command: CycleArtifactCheckInput) -> bool:
    basis = command.original
    assert basis is not None
    outputs = tuple(row.artifact for row in command.manifest.parts)
    expected = {row.artifact_revision_id: row for row in (*basis.inputs.artifacts, *outputs)}
    return (
        command.artifact_kind == basis.artifact_kind == command.manifest.artifact_kind
        and command.target.action_id == command.manifest.action_id
        and command.target.author == basis.author
        and command.target.verifier == basis.verifier
        and command.target.work_snapshot_sha256 == basis.author_registration_sha256
        and command.target.artifacts == outputs
        and {row.artifact_revision_id: row for row in command.inputs.artifacts} == expected
        and command.inputs.contributors == basis.inputs.contributors
        and command.inputs.evidence == basis.inputs.evidence
        and set(basis.inputs.required_resource_ids) <= set(command.inputs.required_resource_ids)
    )


def _result(
    command: CycleArtifactCheckInput, verdict: CheckVerdict, reason: str
) -> CycleArtifactCheckResult:
    payload = CycleArtifactCheckPayload(
        company_id=command.company_id,
        artifact_kind=command.artifact_kind,
        recipe_version=f"stockflow-{command.artifact_kind}-v1",
        target_sha256=canonical_sha256(command.target),
        output_manifest_sha256=canonical_sha256(command.manifest),
        original_basis_sha256=canonical_sha256(command.original) if command.original else None,
        input_snapshot_sha256=canonical_sha256(cycle_check_snapshot(command)),
        verdict=verdict,
        criteria=tuple(
            CriterionCheckResult(criterion_id=key, verdict=verdict, reason=reason)
            for key in command.target.criterion_ids
        ),
    )
    return CycleArtifactCheckResult(**payload.model_dump(), result_sha256=canonical_sha256(payload))
