"""Exact execution/result envelopes remain descriptive until actual M1 authority is checked."""

from __future__ import annotations

import base64
import hashlib
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from nexus.builder.contracts import (
    BuilderArtifact,
    BuilderCommandReceipt,
    BuilderJobSpec,
    BuilderValue,
    Digest,
)
from nexus.builder.node_contracts import NodeRuntimeInputs, absent
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.runtime_identity import RUNTIME_V1, RuntimeRecipe, require_runtime_method
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.canonical import canonical_sha256

RUNTIME_RECIPE: Literal["nexus.builder.runtime.v1"] = "nexus.builder.runtime.v1"
BuilderOutcome = Literal[
    "commands_succeeded",
    "commands_failed",
    "tool_missing",
    "timed_out",
    "cancelled",
    "resource_limited",
    "artifact_export_failed",
    "outcome_unknown",
]


class BuilderExecutionSpec(BuilderValue):
    job: BuilderJobSpec
    policy_sha256: Digest
    runtime_recipe: RuntimeRecipe = RUNTIME_RECIPE
    protected_patch: ArtifactRevisionRef | None = None
    output_resource: ResourceRef | None = None
    runtime_inputs: NodeRuntimeInputs | None = Field(default=None, exclude_if=absent)

    @model_validator(mode="after")
    def exact_patch(self) -> Self:
        if (
            self.output_resource is not None
            and self.output_resource.company_id != self.job.company_id
        ):
            raise ValueError("Builder output resource belongs to another company")
        if (self.job.patch_sha256 is None) != (self.protected_patch is None):
            raise ValueError("Builder patch needs its exact protected artifact reference")
        if self.protected_patch is not None and (
            self.protected_patch.company_id != self.job.company_id
            or self.protected_patch.sha256 != self.job.patch_sha256
            or self.protected_patch.byte_length > 524288
        ):
            raise ValueError("Builder protected patch pin exceeds its exact boundary")
        return self

    def require_policy(self, policy: BuilderToolPolicy) -> None:
        """Existing execution stays v1 until a separately qualified trusted runtime is installed."""
        self.require_descriptive_policy(policy)
        if self.runtime_recipe != RUNTIME_V1:
            raise ValueError("Builder runtime v2 execution is not configured")

    def require_descriptive_policy(self, policy: BuilderToolPolicy) -> None:
        """Pure binding only; it does not authorize a parent, preparation, intent or invocation."""
        require_runtime_method(policy.runtime_recipe, policy.runtime_method_sha256)
        if self.runtime_recipe != policy.runtime_recipe:
            raise ValueError("Builder runtime version differs from the complete policy")
        if self.runtime_inputs != policy.runtime_inputs:
            raise ValueError("Builder runtime inputs differ from the complete policy")
        if canonical_sha256(policy) != self.policy_sha256:
            raise ValueError("Builder policy changed after the exact proposal")


class CapturedFile(BuilderValue):
    metadata: BuilderArtifact
    content_base64: str = Field(max_length=89_478_488)

    @model_validator(mode="after")
    def exact_content(self) -> Self:
        raw = base64.b64decode(self.content_base64, validate=True)
        if (
            len(raw) != self.metadata.byte_length
            or hashlib.sha256(raw).hexdigest() != self.metadata.sha256
        ):
            raise ValueError("Builder captured bytes/hash/length differ")
        return self


class BuilderRunResult(BuilderValue):
    spec: BuilderExecutionSpec
    proposal_sha256: Digest
    intent_fence: int = Field(gt=0, strict=True)
    image_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    container_name: str = Field(pattern=r"^nexus-builder-[0-9a-f]{32}$")
    outcome: BuilderOutcome
    commands: tuple[BuilderCommandReceipt, ...] = Field(default=(), max_length=8)
    artifacts: tuple[CapturedFile, ...] = Field(default=(), max_length=256)
    logs: tuple[CapturedFile, ...] = Field(default=(), max_length=16)
    observed_memory_max: int | None = Field(default=None, ge=1, strict=True)
    observed_cpu_quota: int | None = Field(default=None, ge=1, strict=True)
    observed_cpu_period: int | None = Field(default=None, ge=1, strict=True)
    observed_pids_max: int | None = Field(default=None, ge=1, strict=True)
    recorded_at: AwareDatetime
    elapsed_millis: int = Field(ge=0, strict=True)
    limitations: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def truthful_success(self) -> Self:
        if len(self.commands) > len(self.spec.job.commands):
            raise ValueError("Builder result contains undeclared commands")
        for values in (self.artifacts, self.logs):
            if len({row.metadata.path for row in values}) != len(values):
                raise ValueError("Builder result paths must be distinct")
        if (
            sum(row.metadata.byte_length for row in self.artifacts)
            > self.spec.job.limits.output_bytes
            or sum(row.metadata.byte_length for row in self.logs) > self.spec.job.limits.log_bytes
        ):
            raise ValueError("Builder result exceeds complete capture bounds")
        for index, row in enumerate(self.commands):
            expected = self.spec.job.commands[index]
            if (row.phase, row.command_key) != (expected.phase, expected.command_key):
                raise ValueError("Builder result command order differs from exact job")
        if self.outcome == "commands_succeeded" and (
            len(self.commands) != len(self.spec.job.commands)
            or any(row.outcome != "exited" or row.exit_code != 0 for row in self.commands)
        ):
            raise ValueError("A builder result cannot manufacture missing successful commands")
        return self
