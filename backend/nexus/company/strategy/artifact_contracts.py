"""Exact strategy publication descriptions; decoding grants no effect or owner authority."""

from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.management.base import SHA256, ManagementContract, Name, ValueContract
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactPayload
from nexus.company.strategy.contracts import StrategyScope

StrategyTool = Literal["company.cycle-artifact.write.v1", "company.cycle-artifact.check.v1"]


class StrategyBriefSelector(ValueContract):
    """Original producing scope, never a caller-provided currentness or acceptance flag."""

    scope: StrategyScope


class StrategyWriteParameters(ValueContract):
    selector: StrategyBriefSelector
    recipe_version: Literal["stockflow-strategy-brief-v1"] = "stockflow-strategy-brief-v1"
    output_sha256: SHA256
    input_snapshot_sha256: SHA256
    input_manifest_sha256: SHA256


class StrategyCheckParameters(ValueContract):
    author_action_id: UUID
    verification_target_sha256: SHA256
    recipe_version: Literal["stockflow-strategy-brief-v1"] = "stockflow-strategy-brief-v1"
    output_sha256: SHA256
    input_snapshot_sha256: SHA256


class StrategyArtifactRule(ManagementContract):
    """Server-only closed tool/target/policy configuration, separate from report dispatch."""

    tool: StrategyTool
    tool_version: Literal["v1"] = "v1"
    resource_symbol: Name
    target: ResourceRef
    source_policy: Literal["generated.strategy.v1", "generated.strategy-check.v1"]
    recipe_version: Literal["stockflow-strategy-brief-v1"] = "stockflow-strategy-brief-v1"

    @model_validator(mode="after")
    def exact_policy(self) -> Self:
        expected = (
            "generated.strategy.v1"
            if self.tool == "company.cycle-artifact.write.v1"
            else "generated.strategy-check.v1"
        )
        if self.target.company_id != self.company_id or self.source_policy != expected:
            raise ValueError("Strategy target company or exact tool policy differs")
        return self


class PreparedStrategyArtifact(GeneratedArtifactPayload):
    """Shared bounded byte/manifest mechanics, with a closed strategy-only recipe."""

    recipe_version: Literal["stockflow-strategy-brief-v1"] = "stockflow-strategy-brief-v1"

    @model_validator(mode="after")
    def private_output(self) -> Self:
        if self.data_classification == "public":
            raise ValueError("Strategy publication requires protected output classification")
        return self
