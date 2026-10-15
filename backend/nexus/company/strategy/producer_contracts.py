"""Immutable server narrative and original bundle descriptions, with no publication authority."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.base import (
    SHA256,
    ManagementContract,
    Symbol,
    ValueContract,
    require_company,
)
from nexus.company.strategy.artifact_contracts import PreparedStrategyArtifact
from nexus.company.strategy.contracts import (
    StrategyBrief,
    StrategyCandidate,
    StrategyCheckSnapshot,
    StrategyDecisionRequest,
    StrategyHypothesis,
    StrategyRecommendation,
    StrategyUnknown,
)
from nexus.core.llm.company_registry import DataClassification

STRATEGY_BUNDLE_SERIALIZATION: Literal["strategy-input-bundle-json-v2"] = (
    "strategy-input-bundle-json-v2"
)
MAX_STRATEGY_BUNDLE_BYTES = 2_097_152
MAX_STRATEGY_SOURCE_ARTIFACTS = 30


class StrategyFindingRule(ValueContract):
    """Select exact original evidence; supplied policy cannot replace its quote or date."""

    finding_id: Symbol
    evidence_id: UUID
    hypothesis: StrategyHypothesis | None = None


class StrategyProductionPolicy(ManagementContract):
    """Explicit server-authored narratives, retained immutably beside the original snapshot."""

    scope_sha256: SHA256
    candidate_policy_sha256: SHA256
    data_classification: DataClassification
    finding_rules: tuple[StrategyFindingRule, ...] = Field(min_length=1, max_length=16)
    candidates: tuple[StrategyCandidate, ...] = Field(min_length=2, max_length=2)
    recommendation: StrategyRecommendation
    unknowns: tuple[StrategyUnknown, ...] = Field(min_length=1, max_length=16)
    decision_request: StrategyDecisionRequest

    @model_validator(mode="after")
    def distinct_evidence(self) -> Self:
        if len({row.finding_id for row in self.finding_rules}) != len(self.finding_rules) or len(
            {row.evidence_id for row in self.finding_rules}
        ) != len(self.finding_rules):
            raise ValueError("Strategy production finding and evidence selectors must be unique")
        return self


class StrategyOriginalInputBundle(ManagementContract):
    """Lossless original input wire, separate from canonical semantic identity digests."""

    serialization: Literal["strategy-input-bundle-json-v2"] = STRATEGY_BUNDLE_SERIALIZATION
    snapshot: StrategyCheckSnapshot
    policy: StrategyProductionPolicy

    @model_validator(mode="after")
    def same_company(self) -> Self:
        require_company(self.company_id, self.snapshot, self.policy)
        return self


class StrategyOriginalInputBundleRef(ManagementContract):
    """Byte comparison identity only; does not prove storage, READ, freshness or lineage."""

    serialization: Literal["strategy-input-bundle-json-v2"] = STRATEGY_BUNDLE_SERIALIZATION
    artifact: ArtifactRevisionRef
    resource: ResourceRef
    input_snapshot_sha256: SHA256
    producer_policy_sha256: SHA256

    @model_validator(mode="after")
    def same_company(self) -> Self:
        require_company(self.company_id, self.artifact, self.resource)
        return self


class CompiledStrategy(ValueContract):
    """Mechanical description only; native bundle linkage and independent proof remain required."""

    brief: StrategyBrief
    prepared: PreparedStrategyArtifact
    original_bundle: StrategyOriginalInputBundleRef

    @model_validator(mode="after")
    def same_material(self) -> Self:
        require_company(self.brief.scope.company_id, self.prepared, self.original_bundle)
        if (
            self.prepared.raw_bytes != self.brief.model_dump_json().encode()
            or self.prepared.input_snapshot_sha256 != self.brief.input_snapshot_sha256
            or self.prepared.input_manifest_sha256 != self.brief.input_manifest_sha256
            or self.original_bundle.input_snapshot_sha256 != self.brief.input_snapshot_sha256
        ):
            raise ValueError("Compiled strategy bytes or original input identity differs")
        return self
