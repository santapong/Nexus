"""Trusted selected CSV template descriptions; no READ, approval or runtime authority."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.builder.contracts import (
    Architecture,
    BuilderLimits,
    BuilderValue,
    CommandRef,
    Digest,
    RepositoryPin,
)
from nexus.builder.csv_behavior_wrapper import mapping_sha256
from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
from nexus.builder.node_contracts import NodeRuntimeInputs
from nexus.builder.node_recipe import command_policies, command_references
from nexus.builder.node_v4_assets import csv_wrapper_sha256
from nexus.builder.node_v4_recipe import v4_recipe_sha256
from nexus.builder.paths import relative_path
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.runtime_identity import RUNTIME_V2, RUNTIME_V2_METHOD_SHA256
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.harness.standing_contracts import ToolPermission

CSV_WRITE_PATHS = (
    "packages/shared/src/csv/index.ts",
    "packages/shared/src/csv/csv.test.ts",
)


class SelectedBuilderTemplate(BuilderValue):
    """Exact server configuration only; supplied pins never establish native observation."""

    schema_version: Literal["nexus.builder.selected-strategy-template.v1"] = (
        "nexus.builder.selected-strategy-template.v1"
    )
    company_id: UUID
    goal_id: UUID
    candidate_policy_sha256: Digest
    candidate_scope_sha256: Digest
    repository: RepositoryPin
    source_metadata: ArtifactRevisionRef
    protected_patch: ArtifactRevisionRef
    tool: ToolPermission
    policy: BuilderToolPolicy
    architecture: Architecture
    commands: tuple[CommandRef, ...] = Field(min_length=2, max_length=8)
    write_paths: tuple[str, ...] = Field(min_length=2, max_length=2)
    artifact_paths: tuple[str, ...] = Field(min_length=1, max_length=16)
    limits: BuilderLimits
    output_resource: ResourceRef
    runtime_inputs: NodeRuntimeInputs

    @model_validator(mode="after")
    def exact_configuration(self) -> Self:
        for ref in (self.source_metadata, self.protected_patch, self.policy, self.output_resource):
            if ref.company_id != self.company_id:
                raise ValueError("Selected template company differs")
        pins, policy = self.runtime_inputs, self.policy
        if (
            self.write_paths != CSV_WRITE_PATHS
            or policy.write_paths != self.write_paths
            or self.artifact_paths != policy.artifact_paths
            or len(set(self.artifact_paths)) != len(self.artifact_paths)
            or self.commands != command_references()
            or policy.commands != command_policies()
            or (self.tool.tool, self.tool.tool_version) != ("company.builder.run.v1", "v1")
            or self.tool.resource != policy.resource_symbol
            or self.repository.repository_symbol != policy.repository_symbol
            or self.protected_patch.byte_length > 524288
        ):
            raise ValueError("Selected CSV template scope differs")
        for path in self.artifact_paths:
            relative_path(path)
        if (
            policy.runtime_recipe != RUNTIME_V2
            or policy.runtime_method_sha256 != RUNTIME_V2_METHOD_SHA256
            or policy.full_execution_method_sha256 != CONTAINED_EXECUTION_METHOD_SHA256
            or policy.runtime_inputs != pins
            or pins.recipe != "nexus.builder.node.v4"
            or pins.csv_regression is None
            or pins.command_recipe_sha256 != v4_recipe_sha256()
            or pins.csv_regression.mapping_sha256 != mapping_sha256()
            or pins.csv_regression.wrapper_sha256 != csv_wrapper_sha256()
            or self.architecture != pins.architecture
            or policy.image.split("@sha256:")[-1] != pins.image_id
        ):
            raise ValueError("Selected full implementation, selector or Node CSV pins differ")
        return self
