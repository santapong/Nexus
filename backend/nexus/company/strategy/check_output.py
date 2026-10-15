"""Deterministic SV byte and input identity; supplied data cannot publish or accept work."""

import hashlib
from typing import Self

from pydantic import model_validator

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.base import ValueContract, require_company
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.strategy.artifact_contracts import PreparedStrategyArtifact
from nexus.company.strategy.checker import check_strategy_brief
from nexus.company.strategy.contracts import (
    STRATEGY_CHECK_CRITERIA,
    STRATEGY_CHECK_RECIPE,
    StrategyCheckInput,
    StrategyCheckResult,
    StrategyCheckSnapshot,
)
from nexus.core.llm.company_registry import DataClassification


class StrategyCheckProductionSnapshot(ValueContract):
    """Original target/snapshot/output and complete check manifest, with no clock rewrite."""

    target: VerificationSpec
    snapshot: StrategyCheckSnapshot
    output: ArtifactRevisionRef
    inputs: GeneratedArtifactInputs

    @model_validator(mode="after")
    def complete_description(self) -> Self:
        require_company(self.target.company_id, self.snapshot, self.output, self.inputs)
        original = self.snapshot.inputs
        if (
            self.target.check_recipe != STRATEGY_CHECK_RECIPE
            or self.target.criterion_ids != STRATEGY_CHECK_CRITERIA
            or self.target.artifacts != (self.output,)
            or self.output not in self.inputs.artifacts
            or not set(original.artifacts) <= set(self.inputs.artifacts)
            or self.inputs.contributors != original.contributors
            or self.inputs.evidence != original.evidence
            or not set(original.required_resource_ids) <= set(self.inputs.required_resource_ids)
        ):
            raise ValueError(
                "Strategy check production description lacks its exact original inputs"
            )
        return self


def strategy_check_production_snapshot(
    command: StrategyCheckInput, inputs: GeneratedArtifactInputs
) -> StrategyCheckProductionSnapshot:
    command = StrategyCheckInput.model_validate(command.model_dump(warnings=False))
    require_acceptance(command.snapshot is not None and command.output_utf8 is not None)
    assert command.snapshot is not None and command.output_utf8 is not None
    require_acceptance(
        len(command.output_utf8) == command.output.byte_length
        and hashlib.sha256(command.output_utf8).hexdigest() == command.output.sha256
    )
    return StrategyCheckProductionSnapshot(
        target=command.target,
        snapshot=command.snapshot,
        output=command.output,
        inputs=GeneratedArtifactInputs.model_validate(inputs.model_dump(warnings=False)),
    )


def prepare_strategy_check(
    command: StrategyCheckInput,
    inputs: GeneratedArtifactInputs,
    classification: DataClassification,
) -> PreparedStrategyArtifact:
    """Compile mechanical verdicts; original bundle linkage remains a native-reader gate."""
    production = strategy_check_production_snapshot(command, inputs)
    result = check_strategy_brief(command)
    raw = result.model_dump_json().encode()
    return PreparedStrategyArtifact(
        company_id=command.company_id,
        raw_bytes=raw,
        output_sha256=hashlib.sha256(raw).hexdigest(),
        input_snapshot_sha256=canonical_sha256(production),
        data_classification=classification,
        inputs=production.inputs,
    )


def require_strategy_check_bytes(
    command: StrategyCheckInput,
    inputs: GeneratedArtifactInputs,
    protected: ArtifactRevisionRef,
    raw: bytes,
) -> StrategyCheckResult:
    """Recompute exact result bytes rather than trusting a declared PASS or self-consistent hash."""
    strategy_check_production_snapshot(command, inputs)
    result = check_strategy_brief(command)
    expected = result.model_dump_json().encode()
    require_acceptance(
        protected.company_id == command.company_id
        and 0 < len(raw) <= 262144
        and len(raw) == protected.byte_length
        and hashlib.sha256(raw).hexdigest() == protected.sha256
        and raw == expected
    )
    return result
