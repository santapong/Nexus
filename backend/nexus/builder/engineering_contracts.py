"""Bounded engineering declarations/check descriptions; decoding supplies no authority."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.builder.contracts import BuilderValue, Digest, RepositoryPin
from nexus.builder.execution_contracts import BuilderRunResult
from nexus.builder.paths import relative_path
from nexus.builder.policy import BuilderToolPolicy
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.base import ManagementContract, Name, require_company
from nexus.execution.runtime_contracts import ExecutionRegistration

ENGINEERING_RECIPE: Literal["native-engineering-change-v1"] = "native-engineering-change-v1"
EngineeringVerdict = Literal["pass", "reject", "inconclusive"]
ENGINEERING_CRITERIA = (
    "engineering.patch.v1",
    "engineering.baseline.v1",
    "engineering.post.v1",
    "engineering.behavior.v1",
    "engineering.independent.v1",
    "engineering.sandbox.v1",
    "engineering.artifacts.v1",
)


class EngineeringChangedFile(BuilderValue):
    path: str
    before_sha256: Digest | None
    after_sha256: Digest | None

    @model_validator(mode="after")
    def ordinary_change(self) -> Self:
        relative_path(self.path)
        if self.before_sha256 == self.after_sha256:
            raise ValueError("Engineering witness requires an actual file change")
        return self


class EngineeringSourceWitness(BuilderValue):
    spec_sha256: Digest
    source: RepositoryPin
    patch_sha256: Digest
    baseline_inventory_sha256: Digest
    post_inventory_sha256: Digest
    changes: tuple[EngineeringChangedFile, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def exact_inventory(self) -> Self:
        paths = tuple(row.path for row in self.changes)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("Engineering witness paths must be ordered and distinct")
        if self.baseline_inventory_sha256 == self.post_inventory_sha256:
            raise ValueError("Engineering post inventory must differ from baseline")
        return self


class EngineeringChangeDeclaration(ManagementContract):
    """Server-resolved new goal/recipe/policy basis; never an input-selected approval."""

    goal_id: UUID
    procedure_id: UUID
    recipe: Literal["native-engineering-change-v1"] = ENGINEERING_RECIPE
    policy: BuilderToolPolicy
    image_id: Digest
    author_profile: Literal["engineering.native.v1"] = "engineering.native.v1"
    verifier_profile: Literal["verification.native.v1"] = "verification.native.v1"
    behavior_case_ids: tuple[Name, ...] = Field(min_length=1, max_length=32)
    behavior_artifact: str = "checks/behavior.json"

    @model_validator(mode="after")
    def bounded_method(self) -> Self:
        require_company(self.company_id, self.policy)
        relative_path(self.behavior_artifact)
        if len(set(self.behavior_case_ids)) != len(self.behavior_case_ids):
            raise ValueError("Engineering behavior cases must be exact and unique")
        return self


class EngineeringCheckInput(ManagementContract):
    target: VerificationSpec
    declaration: EngineeringChangeDeclaration
    author: BuilderRunResult
    verifier: BuilderRunResult
    author_receipt: ActionReceipt
    verifier_receipt: ActionReceipt
    author_registration: ExecutionRegistration
    verifier_registration: ExecutionRegistration
    author_output: ArtifactRevisionRef
    verifier_output: ArtifactRevisionRef
    author_witness: EngineeringSourceWitness
    verifier_witness: EngineeringSourceWitness

    @model_validator(mode="after")
    def one_company(self) -> Self:
        require_company(
            self.company_id,
            self.target,
            self.declaration,
            self.author.spec.job,
            self.verifier.spec.job,
            self.author_receipt,
            self.verifier_receipt,
            self.author_output,
            self.verifier_output,
        )
        return self


class EngineeringCriterionResult(BuilderValue):
    criterion_id: Name
    verdict: Literal["pass", "reject", "inconclusive"]
    reason: Name


class EngineeringCheckResult(ManagementContract):
    recipe: Literal["native-engineering-change-v1"] = ENGINEERING_RECIPE
    target_sha256: Digest
    input_sha256: Digest
    author_action_id: UUID
    verifier_action_id: UUID
    author_result_sha256: Digest
    verifier_result_sha256: Digest
    criteria: tuple[EngineeringCriterionResult, ...] = Field(min_length=7, max_length=7)
    verdict: Literal["pass", "reject", "inconclusive"]
    limitations: tuple[Name, ...] = ("mechanical_engineering_only", "business_readiness_unproven")

    @model_validator(mode="after")
    def truthful_verdict(self) -> Self:
        if tuple(row.criterion_id for row in self.criteria) != ENGINEERING_CRITERIA:
            raise ValueError("Engineering check needs every exact closed criterion")
        expected = (
            "reject"
            if any(row.verdict == "reject" for row in self.criteria)
            else "inconclusive"
            if any(row.verdict == "inconclusive" for row in self.criteria)
            else "pass"
        )
        if self.verdict != expected:
            raise ValueError("Engineering verdict differs from its actual criteria")
        return self


class EngineeringBehaviorAssertion(BuilderValue):
    case_id: Name
    status: Literal["pass", "fail", "skip"]


class EngineeringBehaviorEvidence(BuilderValue):
    schema_version: Literal["nexus.engineering.behavior.v1"]
    cases: tuple[EngineeringBehaviorAssertion, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def exact_cases(self) -> Self:
        if len({row.case_id for row in self.cases}) != len(self.cases):
            raise ValueError("Engineering behavior evidence has duplicate assertions")
        return self
