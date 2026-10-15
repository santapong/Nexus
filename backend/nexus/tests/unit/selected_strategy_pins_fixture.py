"""Synthetic selected-builder descriptions only; no READ, native work or runtime proof."""

from dataclasses import dataclass
from uuid import UUID

from nexus.builder.contracts import BuilderJobSpec, BuilderLimits
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256
from nexus.builder.node_recipe import command_policies, command_references
from nexus.builder.policy import BuilderToolPolicy
from nexus.builder.runtime_identity import RUNTIME_V2, RUNTIME_V2_METHOD_SHA256
from nexus.builder.selected_strategy_contracts import SelectedBuilderTemplate
from nexus.builder.selected_strategy_pins import require_selected_builder_spec
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plans import RunBinding
from nexus.company.strategy.contracts import StrategyCandidatePolicy, StrategyCandidateScope
from nexus.tests.node_v4_support import v4_inputs
from nexus.tests.unit.strategy_brief_fixture import strategy_case


@dataclass
class SelectedCase:
    candidate_policy: StrategyCandidatePolicy
    candidate: StrategyCandidateScope
    spec: BuilderExecutionSpec
    policy: BuilderToolPolicy
    template: SelectedBuilderTemplate
    binding: RunBinding
    source_metadata: ArtifactRevisionRef

    def check(self) -> None:
        require_selected_builder_spec(
            self.candidate_policy,
            self.candidate,
            self.spec,
            self.policy,
            self.template,
            self.binding,
            source_metadata=self.source_metadata,
        )


def selected_case(verifier: bool = False) -> SelectedCase:
    """Actual typed objects with synthetic hashes; no filesystem or credential authority."""
    # Keep one >50-line coherent description fixture rather than duplicate its linked pins.
    snapshot = strategy_case().command.snapshot
    assert snapshot is not None
    candidate = snapshot.policy.candidates[0].model_copy(
        update={"method_sha256": CONTAINED_EXECUTION_METHOD_SHA256}
    )
    candidate_policy = snapshot.policy.model_copy(
        update={"candidates": (candidate, snapshot.policy.candidates[1])}
    )
    bound = snapshot.scope.author.model_copy(
        update={
            "task_id": UUID(int=100),
            "actor_id": UUID(int=101),
            "trace_id": UUID(int=102),
            "run_id": UUID(int=103),
            "workflow_name": "engineering.change",
            "model_profile": "engineering.native.v1",
        }
    )
    if verifier:
        bound = bound.model_copy(
            update={
                "task_id": UUID(int=110),
                "actor_id": UUID(int=111),
                "trace_id": UUID(int=112),
                "run_id": UUID(int=113),
                "workflow_name": "engineering.verify",
                "model_profile": "verification.native.v1",
            }
        )
    inputs = v4_inputs()
    assert candidate.tool is not None and candidate.patch_sha256 is not None
    policy = BuilderToolPolicy(
        company_id=bound.company_id,
        policy_symbol="selected.csv.v1",
        resource_symbol=candidate.tool.resource,
        repository_symbol=candidate_policy.repository.repository_symbol,
        image="registry.example/selected@sha256:" + inputs.image_id,
        commands=command_policies(),
        write_paths=candidate.write_paths,
        artifact_paths=("checks",),
        runtime_inputs=inputs,
        runtime_recipe=RUNTIME_V2,
        runtime_method_sha256=RUNTIME_V2_METHOD_SHA256,
        full_execution_method_sha256=CONTAINED_EXECUTION_METHOD_SHA256,
    )
    patch = ArtifactRevisionRef(
        company_id=bound.company_id,
        artifact_id=UUID(int=200),
        artifact_revision_id=UUID(int=201),
        revision="synthetic-patch-v1",
        sha256=candidate.patch_sha256,
        byte_length=400,
    )
    metadata = patch.model_copy(
        update={
            "artifact_id": UUID(int=202),
            "artifact_revision_id": UUID(int=203),
            "sha256": "a" * 64,
        }
    )
    target = ResourceRef(company_id=bound.company_id, resource_id=UUID(int=204))
    job = BuilderJobSpec(
        company_id=bound.company_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
        run_id=bound.run_id,
        workspace_id=bound.workspace_id,
        actor_id=bound.actor_id,
        action_id=UUID(int=205),
        policy_symbol=policy.policy_symbol,
        resource_symbol=policy.resource_symbol,
        architecture=inputs.architecture,
        source=candidate_policy.repository,
        patch_sha256=candidate.patch_sha256,
        write_paths=candidate.write_paths,
        artifact_paths=policy.artifact_paths,
        commands=command_references(),
        limits=BuilderLimits(),
    )
    spec = BuilderExecutionSpec(
        job=job,
        policy_sha256=canonical_sha256(policy),
        runtime_recipe=RUNTIME_V2,
        protected_patch=patch,
        output_resource=target,
        runtime_inputs=inputs,
    )
    template = SelectedBuilderTemplate(
        company_id=bound.company_id,
        goal_id=candidate_policy.goal_id,
        candidate_policy_sha256=canonical_sha256(candidate_policy),
        candidate_scope_sha256=canonical_sha256(candidate),
        repository=candidate_policy.repository,
        source_metadata=metadata,
        protected_patch=patch,
        tool=candidate.tool,
        policy=policy,
        architecture=inputs.architecture,
        commands=job.commands,
        write_paths=job.write_paths,
        artifact_paths=job.artifact_paths,
        limits=job.limits,
        output_resource=target,
        runtime_inputs=inputs,
    )
    return SelectedCase(candidate_policy, candidate, spec, policy, template, bound, metadata)
