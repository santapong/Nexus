"""Pure selected-builder comparisons; actual source bytes and native authority remain separate."""

from nexus.builder.contracts import BuilderLimits
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.runtime_identity import RUNTIME_V2
from nexus.builder.selected_strategy_contracts import SelectedBuilderTemplate
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plans import RunBinding
from nexus.company.strategy.contracts import StrategyCandidatePolicy, StrategyCandidateScope


def _raw_counts(
    spec: BuilderExecutionSpec,
    template: SelectedBuilderTemplate,
    source_metadata: ArtifactRevisionRef,
) -> None:
    # Serialization can normalize copied values; check their actual types first.
    for limits in (spec.job.limits, template.limits):
        if not isinstance(limits, BuilderLimits):
            raise ValueError("Selected builder limits are unavailable")
        BuilderLimits.model_validate(
            {name: getattr(limits, name) for name in BuilderLimits.model_fields}
        )
    for ref in (
        source_metadata,
        template.source_metadata,
        template.protected_patch,
        spec.protected_patch,
    ):
        if not isinstance(ref, ArtifactRevisionRef) or type(ref.byte_length) is not int:
            raise ValueError("Selected builder reference length is not an exact integer")


def require_selected_builder_spec(
    candidate_policy: StrategyCandidatePolicy,
    candidate: StrategyCandidateScope,
    spec: BuilderExecutionSpec,
    policy: BuilderToolPolicy,
    template: SelectedBuilderTemplate,
    binding: RunBinding,
    *,
    source_metadata: ArtifactRevisionRef,
) -> None:
    """Compare supplied descriptions, without proving a current plan, quota, READ or permit."""
    # Keep complete revalidation and exact job/template binding in this >50-line pure boundary.
    _raw_counts(spec, template, source_metadata)
    candidate_policy = StrategyCandidatePolicy.model_validate(
        candidate_policy.model_dump(warnings=False)
    )
    candidate = StrategyCandidateScope.model_validate(candidate.model_dump(warnings=False))
    spec = BuilderExecutionSpec.model_validate(spec.model_dump(warnings=False))
    policy = BuilderToolPolicy.model_validate(policy.model_dump(warnings=False))
    template = SelectedBuilderTemplate.model_validate(template.model_dump(warnings=False))
    binding = RunBinding.model_validate(binding.model_dump(warnings=False))
    source_metadata = ArtifactRevisionRef.model_validate(source_metadata.model_dump(warnings=False))
    job = spec.job
    if (
        candidate.kind != "change"
        or tuple(row for row in candidate_policy.candidates if row == candidate) != (candidate,)
        or canonical_sha256(candidate_policy) != template.candidate_policy_sha256
        or canonical_sha256(candidate) != template.candidate_scope_sha256
        or candidate_policy.goal_id != template.goal_id
        or candidate.method_sha256 != CONTAINED_EXECUTION_METHOD_SHA256
        or candidate.tool != template.tool
        or candidate.write_paths != template.write_paths
        or candidate.patch_sha256 != template.protected_patch.sha256
        or candidate_policy.repository != template.repository
        or candidate_policy.company_id != template.company_id
    ):
        raise ValueError("Selected original candidate policy or scope differs")
    if (
        (binding.workflow_name, binding.workflow_version, binding.model_profile)
        not in {
            ("engineering.change", "v1", "engineering.native.v1"),
            ("engineering.verify", "v1", "verification.native.v1"),
        }
        or (
            job.company_id,
            job.workspace_id,
            job.actor_id,
            job.task_id,
            job.trace_id,
            job.run_id,
        )
        != (
            binding.company_id,
            binding.workspace_id,
            binding.actor_id,
            binding.task_id,
            binding.trace_id,
            binding.run_id,
        )
        or job.company_id != template.company_id
    ):
        raise ValueError("Selected closed native role description differs")
    spec.require_descriptive_policy(policy)
    if (
        policy != template.policy
        or spec.runtime_recipe != RUNTIME_V2
        or spec.runtime_inputs != template.runtime_inputs
        or source_metadata != template.source_metadata
        or spec.protected_patch != template.protected_patch
        or spec.output_resource != template.output_resource
        or job.source != template.repository
        or job.patch_sha256 != candidate.patch_sha256
        or job.policy_symbol != policy.policy_symbol
        or job.resource_symbol != template.tool.resource
        or job.architecture != template.architecture
        or job.commands != template.commands
        or job.write_paths != template.write_paths
        or job.artifact_paths != template.artifact_paths
        or job.limits != template.limits
    ):
        raise ValueError("Selected exact builder descriptor differs")
