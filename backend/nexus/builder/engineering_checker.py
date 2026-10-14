"""Deterministic bounded engineering checks; even pass is not publication authority."""

from __future__ import annotations

from nexus.builder.engineering_behavior import check_behavior
from nexus.builder.engineering_contracts import (
    ENGINEERING_CRITERIA,
    ENGINEERING_RECIPE,
    EngineeringCheckInput,
    EngineeringCheckResult,
    EngineeringCriterionResult,
    EngineeringVerdict,
)
from nexus.builder.execution_contracts import BuilderRunResult
from nexus.builder.paths import permitted_path
from nexus.builder.result_store import BuilderResultStore
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plans import RunBinding
from nexus.execution.runtime_support import registration_digest


def check_engineering_change(value: EngineeringCheckInput) -> EngineeringCheckResult:
    value = EngineeringCheckInput.model_validate_json(value.model_dump_json())
    results = (
        _patch(value),
        _phase(value, "baseline"),
        _phase(value, "post"),
        check_behavior(value),
        _independent(value),
        _sandbox(value),
        _artifacts(value),
    )
    criteria = tuple(
        EngineeringCriterionResult(criterion_id=key, verdict=verdict, reason=reason)
        for key, (verdict, reason) in zip(ENGINEERING_CRITERIA, results, strict=True)
    )
    verdict: EngineeringVerdict = (
        "reject"
        if any(row.verdict == "reject" for row in criteria)
        else "inconclusive"
        if any(row.verdict == "inconclusive" for row in criteria)
        else "pass"
    )
    return EngineeringCheckResult(
        company_id=value.company_id,
        target_sha256=canonical_sha256(value.target),
        input_sha256=canonical_sha256(value),
        author_action_id=value.author.spec.job.action_id,
        verifier_action_id=value.verifier.spec.job.action_id,
        author_result_sha256=BuilderResultStore.digest(value.author),
        verifier_result_sha256=BuilderResultStore.digest(value.verifier),
        criteria=criteria,
        verdict=verdict,
    )


def _patch(value: EngineeringCheckInput) -> tuple[EngineeringVerdict, str]:
    first, second = value.author.spec, value.verifier.spec
    if first.protected_patch is None or second.protected_patch is None:
        return "reject", "nonempty_protected_patch_required"
    if first.protected_patch != second.protected_patch or first.protected_patch.byte_length == 0:
        return "reject", "independent_patch_reference_differs"
    if first.job.source != second.job.source:
        return "reject", "independent_source_pin_differs"
    for result, witness in (
        (value.author, value.author_witness),
        (value.verifier, value.verifier_witness),
    ):
        if (
            witness.spec_sha256 != canonical_sha256(result.spec)
            or witness.source != result.spec.job.source
            or witness.patch_sha256 != result.spec.job.patch_sha256
            or any(
                not permitted_path(row.path, value.declaration.policy.write_paths)
                for row in witness.changes
            )
        ):
            return "reject", "actual_source_patch_inventory_differs"
    if (
        value.author_witness.baseline_inventory_sha256,
        value.author_witness.post_inventory_sha256,
        value.author_witness.changes,
    ) != (
        value.verifier_witness.baseline_inventory_sha256,
        value.verifier_witness.post_inventory_sha256,
        value.verifier_witness.changes,
    ):
        return "reject", "independent_source_inventories_differ"
    return "pass", "exact_protected_patch_and_independent_inventories"


def _phase(value: EngineeringCheckInput, phase: str) -> tuple[EngineeringVerdict, str]:
    for result in (value.author, value.verifier):
        declared = tuple(row for row in result.spec.job.commands if row.phase == phase)
        actual = tuple(row for row in result.commands if row.phase == phase)
        if any(row.outcome != "exited" or row.exit_code != 0 for row in actual):
            return "reject", phase + "_command_failed"
        if not declared or len(actual) != len(declared) or result.outcome != "commands_succeeded":
            return "inconclusive", phase + "_complete_success_unavailable"
    return "pass", phase + "_actual_complete_success"


def _binding(result: BuilderRunResult, bound: RunBinding) -> bool:
    job = result.spec.job
    return (
        job.company_id,
        job.task_id,
        job.trace_id,
        job.run_id,
        job.actor_id,
        job.workspace_id,
    ) == (
        bound.company_id,
        bound.task_id,
        bound.trace_id,
        bound.run_id,
        bound.actor_id,
        bound.workspace_id,
    )


def _receipt(receipt: ActionReceipt, result: BuilderRunResult, output: ArtifactRevisionRef) -> bool:
    job = result.spec.job
    return (
        (
            receipt.action_id,
            receipt.task_id,
            receipt.trace_id,
            receipt.proposal_hash,
            receipt.outcome,
        )
        == (job.action_id, job.task_id, job.trace_id, result.proposal_sha256, "succeeded")
        and len(receipt.artifacts) == 1
        and (
            receipt.artifacts[0].artifact_id,
            receipt.artifacts[0].revision,
            receipt.artifacts[0].sha256,
        )
        == (output.artifact_id, output.revision, output.sha256)
    )


def _independent(value: EngineeringCheckInput) -> tuple[EngineeringVerdict, str]:
    target = value.target
    if target.check_recipe != ENGINEERING_RECIPE or target.criterion_ids != ENGINEERING_CRITERIA:
        return "reject", "registered_engineering_recipe_or_criteria_differs"
    if not _binding(value.author, target.author) or not _binding(value.verifier, target.verifier):
        return "reject", "actual_author_verifier_binding_differs"
    if (target.author.model_profile, target.verifier.model_profile) != (
        value.declaration.author_profile,
        value.declaration.verifier_profile,
    ):
        return "reject", "declared_execution_profiles_differ"
    if (
        target.author.workflow_name,
        target.author.workflow_version,
        target.verifier.workflow_name,
        target.verifier.workflow_version,
    ) != ("engineering.change", "v1", "engineering.verify", "v1"):
        return "reject", "declared_execution_workflows_differ"
    if not _registrations(value):
        return "reject", "new_native_goal_or_zero_model_allowance_differs"
    if value.author.spec.job.action_id == value.verifier.spec.job.action_id:
        return "reject", "independent_action_required"
    if (
        target.action_id,
        target.receipt_id,
        target.receipt_sha256,
        target.proposal_sha256,
        target.work_snapshot_sha256,
        target.artifacts,
    ) != (
        value.author_receipt.action_id,
        value.author_receipt.receipt_id,
        canonical_sha256(value.author_receipt),
        value.author.proposal_sha256,
        registration_digest(value.author_registration),
        (value.author_output,),
    ):
        return "reject", "actual_registered_target_receipt_differs"
    if not (
        _receipt(value.author_receipt, value.author, value.author_output)
        and _receipt(value.verifier_receipt, value.verifier, value.verifier_output)
    ):
        return "reject", "actual_native_output_receipt_differs"
    for spec in (value.author.spec, value.verifier.spec):
        try:
            spec.require_policy(value.declaration.policy)
        except ValueError:
            return "reject", "complete_declared_policy_differs"
    return "pass", "distinct_exact_native_author_verifier_receipts"


def _registrations(value: EngineeringCheckInput) -> bool:
    for registration, binding in (
        (value.author_registration, value.target.author),
        (value.verifier_registration, value.target.verifier),
    ):
        if (
            registration.work.company_id,
            registration.work.task_id,
            registration.work.trace_id,
            registration.work.goal_id,
            registration.work.acceptance,
            registration.run_id,
            registration.workflow_name,
            registration.workflow_version,
            registration.model_profile,
            registration.model_registry_version,
            registration.quota.model_requests,
        ) != (
            binding.company_id,
            binding.task_id,
            binding.trace_id,
            value.declaration.goal_id,
            ENGINEERING_CRITERIA,
            binding.run_id,
            binding.workflow_name,
            binding.workflow_version,
            binding.model_profile,
            binding.model_registry_version,
            0,
        ):
            return False
    return True


def _sandbox(value: EngineeringCheckInput) -> tuple[EngineeringVerdict, str]:
    for result in (value.author, value.verifier):
        quota, period = result.observed_cpu_quota, result.observed_cpu_period
        memory, pids = result.observed_memory_max, result.observed_pids_max
        if any(row is None for row in (quota, period, memory, pids)):
            return "inconclusive", "actual_kernel_enforcement_unavailable"
        assert quota is not None and period is not None and memory is not None and pids is not None
        limit = result.spec.job.limits
        if (
            result.image_id != value.declaration.image_id
            or memory > limit.memory_bytes
            or pids > limit.pids
            or quota * 1000 > limit.cpu_millis * period
        ):
            return "reject", "actual_image_or_kernel_limits_differ"
    if (
        value.author.spec.job.architecture,
        value.author.spec.runtime_recipe,
        value.author.spec.runtime_inputs,
        value.author.spec.job.commands,
        value.author.spec.job.limits,
    ) != (
        value.verifier.spec.job.architecture,
        value.verifier.spec.runtime_recipe,
        value.verifier.spec.runtime_inputs,
        value.verifier.spec.job.commands,
        value.verifier.spec.job.limits,
    ):
        return "reject", "independent_runtime_method_differs"
    return "pass", "exact_actual_kernel_and_runtime_method"


def _artifacts(value: EngineeringCheckInput) -> tuple[EngineeringVerdict, str]:
    for result in (value.author, value.verifier):
        if any(
            not any(
                row.metadata.path.startswith(f"{phase}/{path}/")
                or row.metadata.path == f"{phase}/{path}"
                for row in result.artifacts
            )
            for phase in ("baseline", "post")
            for path in result.spec.job.artifact_paths
        ):
            return "inconclusive", "declared_phase_artifacts_unavailable"
    return "pass", "actual_bounded_declared_phase_artifacts"
