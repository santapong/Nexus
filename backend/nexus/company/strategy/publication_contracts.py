"""Exact B/Brief publication descriptions; only current native records authorize writes."""

from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.base import ManagementContract, ValueContract, require_company
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.strategy.artifact_contracts import StrategyArtifactRule
from nexus.company.strategy.artifact_identity import strategy_reference
from nexus.company.strategy.producer import prepare_strategy_artifact, strategy_input_bundle_bytes
from nexus.company.strategy.producer_contracts import (
    CompiledStrategy,
    StrategyOriginalInputBundle,
    StrategyOriginalInputBundleRef,
)
from nexus.company.strategy.publication_identity import strategy_bundle_reference


class StrategyPublicationRules(ManagementContract):
    """One server-configured write/check pair and exact protected derived policies."""

    write: StrategyArtifactRule
    check: StrategyArtifactRule
    bundle_policy: SourcePolicy
    brief_policy: SourcePolicy
    check_policy: SourcePolicy

    @model_validator(mode="after")
    def exact_tools_and_policies(self) -> Self:
        require_company(self.company_id, self.write, self.check)
        if (
            self.write.tool != "company.cycle-artifact.write.v1"
            or self.check.tool != "company.cycle-artifact.check.v1"
            or self.bundle_policy.source_symbol != "generated.strategy-inputs.v2"
            or self.brief_policy.source_symbol != self.write.source_policy
            or self.check_policy.source_symbol != self.check.source_policy
            or self.bundle_policy.max_bytes != 2_097_152
            or self.brief_policy.max_bytes > 262_144
            or self.check_policy.max_bytes > 262_144
            or self.bundle_policy.data_classification != self.brief_policy.data_classification
            or any(
                row.origin_kind != "derived"
                or row.media_type != "application/json"
                or row.data_classification == "public"
                for row in (self.bundle_policy, self.brief_policy, self.check_policy)
            )
        ):
            raise ValueError("Strategy publication requires exact protected server tools/policies")
        return self


class PreparedStrategyPublication(ValueContract):
    """Full original B and exact Brief/M description; no issued intent or acceptance flag."""

    action_id: UUID
    original: StrategyOriginalInputBundle
    bundle_bytes: bytes = Field(min_length=1, max_length=2_097_152)
    compiled: CompiledStrategy
    brief: ArtifactRevisionRef

    @model_validator(mode="after")
    def exact_material(self) -> Self:
        original = StrategyOriginalInputBundle.model_validate(
            self.original.model_dump(warnings=False)
        )
        snapshot, policy = original.snapshot, original.policy
        raw = strategy_input_bundle_bytes(snapshot, policy)
        expected = strategy_bundle_reference(
            original.company_id,
            self.action_id,
            raw,
            canonical_sha256(snapshot),
            canonical_sha256(policy),
            self.compiled.original_bundle.resource,
        )
        if (
            self.bundle_bytes != raw
            or self.compiled
            != prepare_strategy_artifact(snapshot, policy, original_bundle=expected)
            or self.brief != strategy_reference(self.compiled.prepared, self.action_id)
        ):
            raise ValueError("Strategy publication exact original bytes/identities differ")
        # Reserve the complete future SV input view while keeping original M unchanged.
        GeneratedArtifactInputs(
            **snapshot.inputs.model_dump(exclude={"artifacts"}),
            artifacts=(*snapshot.inputs.artifacts, expected.artifact, self.brief),
        )
        return self


class StrategyPublishedArtifacts(ManagementContract):
    """Native return references only; a receipt and independent acceptance remain separate."""

    bundle: StrategyOriginalInputBundleRef
    brief: ArtifactRevisionRef

    @model_validator(mode="after")
    def same_company(self) -> Self:
        require_company(self.company_id, self.bundle, self.brief)
        return self


class StrategyLoadedPublication(ValueContract):
    """Actual reader facts; a caller-created DTO cannot establish current protected READ."""

    prepared: PreparedStrategyPublication
    action: ActionProposal
    receipt: ActionReceipt
    original_intent_fence: int = Field(gt=0, strict=True)
