"""Bounded original deliverable basis; construction establishes no current/native authority."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.cycle_artifacts.common import CycleKind, criteria_for, digest
from nexus.company.cycle_artifacts.engineering import EngineeringBasis
from nexus.company.management.base import SHA256, ManagementContract, require_company
from nexus.company.management.check_contracts import SourceQuoteClaim
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.plans import RunBinding
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionRegistration
from nexus.execution.runtime_support import registration_digest


class CycleArtifactBasis(ManagementContract):
    """Original supplied-data snapshot, separately requalified by a future native reader."""

    artifact_kind: CycleKind
    goal: GoalRevisionRef
    producing_plan: PlanRevisionRef
    procedure_id: UUID
    author: RunBinding
    verifier: RunBinding
    author_registration: ExecutionRegistration
    author_registration_sha256: SHA256
    observed_at: AwareDatetime
    engineering: EngineeringBasis
    inputs: GeneratedArtifactInputs
    citations: tuple[SourceQuoteClaim, ...] = Field(min_length=1, max_length=16)
    target: ResourceRef
    data_classification: Literal["internal", "confidential", "restricted"]

    @model_validator(mode="after")
    def exact_snapshot(self) -> Self:
        require_company(
            self.company_id,
            self.goal,
            self.producing_plan,
            self.author,
            self.verifier,
            self.author_registration.work,
            self.engineering,
            self.inputs,
            self.target,
        )
        _registration(self)
        if (
            self.producing_plan.revision != 2
            or self.engineering.goal_id != self.goal.goal_id
            or self.engineering.procedure_id != self.procedure_id
            or self.engineering.acceptance.target.author.workspace_id != self.author.workspace_id
            or self.author.actor_id == self.verifier.actor_id
            or self.author.task_id == self.verifier.task_id
            or self.author.workspace_id != self.verifier.workspace_id
            or (
                self.verifier.workflow_name,
                self.verifier.workflow_version,
                self.verifier.model_profile,
                self.verifier.model_registry_version,
            )
            != ("company.cycle.artifact", "v1", "verification", self.author.model_registry_version)
        ):
            raise ValueError("Cycle original scope or independent role bindings differ")
        _manifest(self)
        return self


def checked_basis(value: CycleArtifactBasis) -> CycleArtifactBasis:
    """Validate raw copied quotas before a serializer can normalize bool/float/string values."""
    quota = value.author_registration.quota
    AttemptQuota.model_validate({k: getattr(quota, k) for k in AttemptQuota.model_fields})
    return CycleArtifactBasis.model_validate(value.model_dump(warnings=False))


def _registration(value: CycleArtifactBasis) -> None:
    row, binding = value.author_registration, value.author
    quota = AttemptQuota.model_validate(
        {k: getattr(row.quota, k) for k in AttemptQuota.model_fields}
    )
    if (
        quota != AttemptQuota(model_requests=1, tool_attempts=1, rework_rounds=0, plan_revisions=0)
        or (
            row.work.task_id,
            row.work.trace_id,
            row.run_id,
            row.workflow_name,
            row.workflow_version,
            row.model_profile,
            row.model_registry_version,
        )
        != (
            binding.task_id,
            binding.trace_id,
            binding.run_id,
            binding.workflow_name,
            binding.workflow_version,
            binding.model_profile,
            binding.model_registry_version,
        )
        or (binding.workflow_name, binding.workflow_version, binding.model_profile)
        != ("company.cycle.artifact", "v1", "routine")
        or row.work.goal_id != value.goal.goal_id
        or row.work.acceptance != criteria_for(value.artifact_kind)
        or row.work.depends_on != (value.engineering.acceptance.target.author.task_id,)
        or registration_digest(row) != value.author_registration_sha256
    ):
        raise ValueError("Cycle original registration/quota/criteria/dependency/hash differs")


def _manifest(value: CycleArtifactBasis) -> None:
    engineering, inputs = value.engineering, value.inputs
    required = (engineering.author_summary, engineering.verifier_summary, engineering.check)
    artifacts = {row.artifact_revision_id: row for row in inputs.artifacts}
    evidence_ids = {row.evidence_id for row in inputs.evidence}
    if (
        any(artifacts.get(row.artifact_revision_id) != row for row in required)
        or len({row.evidence_id for row in value.citations}) != len(value.citations)
        or any(
            row.evidence_id not in evidence_ids
            or row.artifact_revision_id not in artifacts
            or row.source_revision_id not in {s.source_revision_id for s in inputs.contributors}
            or row.source_state != "current"
            or row.freshness != "fresh"
            or "\0" in row.quote
            or digest(row.quote.encode()) != row.span_sha256
            for row in value.citations
        )
        or max(
            engineering.acceptance.recorded_at,
            engineering.author_receipt.recorded_at,
            engineering.verifier_receipt.recorded_at,
        )
        > value.observed_at
    ):
        raise ValueError("Cycle declared complete input/quotation/date basis differs")
