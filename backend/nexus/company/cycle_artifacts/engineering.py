"""Supplied engineering evidence comparison; even exact bytes are not actual native proof."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.builder.contained_evidence_types import ContainmentRef
from nexus.builder.contracts import BuilderArtifact, BuilderCommandReceipt, RepositoryPin
from nexus.builder.engineering_contracts import (
    ENGINEERING_CRITERIA,
    ENGINEERING_RECIPE,
    EngineeringCheckResult,
    EngineeringSourceWitness,
)
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.cycle_artifacts.common import bounded_json, digest
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.base import SHA256, ManagementContract, ValueContract, require_company
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plans import RunBinding
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionRegistration
from nexus.execution.runtime_support import registration_digest


class EngineeringSummary(ValueContract):
    result_sha256: SHA256
    spec: BuilderExecutionSpec
    proposal_sha256: SHA256
    intent_fence: int = Field(gt=0, strict=True)
    outcome: Literal["commands_succeeded"]
    commands: tuple[BuilderCommandReceipt, ...] = Field(min_length=2, max_length=8)
    artifacts: tuple[BuilderArtifact, ...] = Field(max_length=256)
    logs: tuple[BuilderArtifact, ...] = Field(max_length=16)
    limitations: tuple[str, ...] = Field(max_length=16)
    containment: ContainmentRef | None = None
    engineering_source_witness: EngineeringSourceWitness | None = None


class EngineeringEvidence(ManagementContract):
    """Input descriptions for pure comparison; a concrete reader must supply actual records."""

    acceptance: WorkAcceptance
    procedure_id: UUID
    author_registration: ExecutionRegistration
    verifier_registration: ExecutionRegistration
    author_receipt: ActionReceipt
    verifier_receipt: ActionReceipt
    author_summary: ArtifactRevisionRef
    author_utf8: bytes = Field(min_length=1, max_length=262144)
    verifier_summary: ArtifactRevisionRef
    verifier_utf8: bytes = Field(min_length=1, max_length=262144)
    check: ArtifactRevisionRef
    check_utf8: bytes = Field(min_length=1, max_length=16384)


class EngineeringBasis(ManagementContract):
    """Closed projection only; no native-current, sandbox or deployment affirmation."""

    acceptance: WorkAcceptance
    procedure_id: UUID
    goal_id: UUID
    author_registration_sha256: SHA256
    verifier_registration_sha256: SHA256
    author_receipt: ActionReceipt
    verifier_receipt: ActionReceipt
    author_summary: ArtifactRevisionRef
    verifier_summary: ArtifactRevisionRef
    check: ArtifactRevisionRef
    author_result_sha256: SHA256
    verifier_result_sha256: SHA256
    source: RepositoryPin
    patch_sha256: SHA256
    check_recipe: Literal["native-engineering-change-v1"] = ENGINEERING_RECIPE
    behavior_detail: Literal["not_observed"] = "not_observed"

    @model_validator(mode="after")
    def exact_links(self) -> Self:
        require_company(
            self.company_id,
            self.acceptance,
            self.author_receipt,
            self.verifier_receipt,
            self.author_summary,
            self.verifier_summary,
            self.check,
        )
        target = self.acceptance.target
        if (
            self.acceptance.verdict != "pass"
            or target.check_recipe != ENGINEERING_RECIPE
            or target.criterion_ids != ENGINEERING_CRITERIA
            or target.artifacts != (self.author_summary,)
            or len(self.acceptance.proofs) != 1
            or self.acceptance.proofs[0].result_artifact != self.check
            or target.action_id != self.author_receipt.action_id
            or target.proposal_sha256 != self.author_receipt.proposal_hash
            or target.receipt_id != self.author_receipt.receipt_id
            or target.receipt_sha256 != canonical_sha256(self.author_receipt)
        ):
            raise ValueError("Cycle engineering projection differs from exact acceptance links")
        return self


def compare_engineering_evidence(value: EngineeringEvidence) -> EngineeringBasis:
    """Recompute supplied summary/proof links without claiming actual SQL/sidecar authority."""
    # Keep this >50-line supplied receipt/registration/result projection comparison cohesive.
    for row in (value.author_registration, value.verifier_registration):
        AttemptQuota.model_validate({k: getattr(row.quota, k) for k in AttemptQuota.model_fields})
    value = EngineeringEvidence.model_validate(value.model_dump(warnings=False))
    first = _summary(value.author_utf8, value.author_summary)
    second = _summary(value.verifier_utf8, value.verifier_summary)
    bounded_json(value.check_utf8, maximum=16384)
    result = EngineeringCheckResult.model_validate_json(value.check_utf8)
    if (
        digest(value.check_utf8) != value.check.sha256
        or len(value.check_utf8) != value.check.byte_length
    ):
        raise ValueError("Supplied engineering check bytes differ from exact reference")
    target = value.acceptance.target
    _registration(value.author_registration, target.author, "engineering.native.v1")
    _registration(value.verifier_registration, target.verifier, "verification.native.v1")
    _receipt(value.author_receipt, first, target.author, value.author_summary)
    _receipt(value.verifier_receipt, second, target.verifier, value.verifier_summary)
    if (
        result.company_id != value.company_id
        or result.verdict != "pass"
        or result.target_sha256 != canonical_sha256(target)
        or result.author_action_id != value.author_receipt.action_id
        or result.verifier_action_id != value.verifier_receipt.action_id
        or result.author_result_sha256 != first.result_sha256
        or result.verifier_result_sha256 != second.result_sha256
        or first.spec.job.source != second.spec.job.source
        or first.spec.job.patch_sha256 is None
        or first.spec.protected_patch is None
        or first.spec.protected_patch.sha256 != first.spec.job.patch_sha256
        or first.spec.protected_patch != second.spec.protected_patch
        or first.spec.job.patch_sha256 != second.spec.job.patch_sha256
        or result.limitations != ("mechanical_engineering_only", "business_readiness_unproven")
        or max(value.author_receipt.recorded_at, value.verifier_receipt.recorded_at)
        > value.acceptance.recorded_at
        or value.author_registration.work.goal_id != value.verifier_registration.work.goal_id
        or target.work_snapshot_sha256 != registration_digest(value.author_registration)
    ):
        raise ValueError("Supplied engineering evidence differs from the exact mechanical basis")
    return EngineeringBasis(
        **value.model_dump(
            exclude={
                "author_utf8",
                "verifier_utf8",
                "check_utf8",
                "author_registration",
                "verifier_registration",
            }
        ),
        goal_id=value.author_registration.work.goal_id,
        author_registration_sha256=registration_digest(value.author_registration),
        verifier_registration_sha256=registration_digest(value.verifier_registration),
        author_result_sha256=first.result_sha256,
        verifier_result_sha256=second.result_sha256,
        source=first.spec.job.source,
        patch_sha256=first.spec.job.patch_sha256,
    )


def _registration(row: ExecutionRegistration, binding: RunBinding, profile: str) -> None:
    if (
        row.work.company_id != binding.company_id
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
        or row.work.acceptance != ENGINEERING_CRITERIA
        or row.model_profile != profile
        or row.quota
        != AttemptQuota(model_requests=0, tool_attempts=1, rework_rounds=0, plan_revisions=0)
    ):
        raise ValueError("Supplied native engineering registration differs")


def _summary(raw: bytes, ref: ArtifactRevisionRef) -> EngineeringSummary:
    bounded_json(raw)
    if digest(raw) != ref.sha256 or len(raw) != ref.byte_length:
        raise ValueError("Supplied engineering summary bytes differ from exact reference")
    result = EngineeringSummary.model_validate_json(raw)
    if (
        tuple((r.phase, r.command_key) for r in result.commands)
        != tuple((r.phase, r.command_key) for r in result.spec.job.commands)
        or {r.phase for r in result.commands} != {"baseline", "post"}
        or any(r.outcome != "exited" or r.exit_code != 0 for r in result.commands)
    ):
        raise ValueError("Supplied engineering summary lacks complete baseline/post success")
    return result


def _receipt(
    receipt: ActionReceipt,
    summary: EngineeringSummary,
    binding: RunBinding,
    ref: ArtifactRevisionRef,
) -> None:
    job = summary.spec.job
    if (
        (job.company_id, job.task_id, job.trace_id, job.run_id, job.actor_id, job.workspace_id)
        != (
            binding.company_id,
            binding.task_id,
            binding.trace_id,
            binding.run_id,
            binding.actor_id,
            binding.workspace_id,
        )
        or (
            receipt.company_id,
            receipt.task_id,
            receipt.trace_id,
            receipt.action_id,
            receipt.proposal_hash,
            receipt.outcome,
        )
        != (
            job.company_id,
            job.task_id,
            job.trace_id,
            job.action_id,
            summary.proposal_sha256,
            "succeeded",
        )
        or len(receipt.artifacts) != 1
        or (
            receipt.artifacts[0].company_id,
            receipt.artifacts[0].artifact_id,
            receipt.artifacts[0].revision,
            receipt.artifacts[0].sha256,
        )
        != (ref.company_id, ref.artifact_id, ref.revision, ref.sha256)
    ):
        raise ValueError("Supplied engineering receipt/summary/work links differ")
