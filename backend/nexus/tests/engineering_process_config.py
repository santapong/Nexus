"""Bounded process fixture inputs carry no permits, credentials or keys."""

from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from nexus.builder.contracts import BuilderCapabilities, Digest
from nexus.builder.engineering_artifacts import EngineeringArtifactPublisher
from nexus.builder.engineering_contracts import EngineeringChangeDeclaration
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.policy import BuilderToolPolicy
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.base import ValueContract, require_company
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.plans import RunBinding
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.engineering_dispatch_read import engineering_phase, require_command_binding
from nexus.tests.engineering_pending_contracts import PendingEngineeringScenario
from nexus.tests.engineering_process_scope import require_process_root


class EngineeringProcessConfig(ValueContract):
    """Typed fixture data rebuilds services without a credential or call permit."""

    catalog: PlanAdmissionCatalog
    declaration: EngineeringChangeDeclaration
    policy: BuilderToolPolicy
    capabilities: BuilderCapabilities
    image_id: Digest
    database: str
    task_root: Path
    source_root: Path
    source_metadata: ArtifactRevisionRef
    output_target: ResourceRef
    proof_target: ResourceRef
    policies: tuple[SourcePolicy, ...] = Field(min_length=1, max_length=32)
    verifier_binding: RunBinding
    verifier_action: ActionProposal
    verifier_spec: BuilderExecutionSpec
    workflow_id: UUID
    command: SegmentCommand
    lease_ttl_seconds: Literal[10, 30] = 10

    @model_validator(mode="after")
    def exact_reviewed_scope(self) -> Self:
        require_process_root(self.database, self.task_root, existing=True)
        expected_ttl = (
            30 if self.database.startswith("nexus_company_test_engineering_immediate_") else 10
        )
        if self.lease_ttl_seconds != expected_ttl:
            raise ValueError("Engineering fixture lease TTL differs from reviewed case")
        if self.source_root != self.task_root / "harmless-engineering-repository":
            raise ValueError("Engineering process source root differs")
        if self.source_root.resolve() != self.source_root or not self.source_root.is_dir():
            raise ValueError("Engineering process source root is unavailable")
        require_company(
            self.command.company_id,
            self.catalog,
            self.declaration,
            self.policy,
            self.source_metadata,
            self.output_target,
            self.proof_target,
            self.verifier_binding,
            self.verifier_action,
            self.verifier_spec.job,
        )
        self.require_command_spec()
        if self.declaration.policy != self.policy or self.declaration.image_id != self.image_id:
            raise ValueError("Engineering process declaration pins differ")
        if (
            self.verifier_spec.output_resource != self.output_target
            or self.policy.image != self.capabilities.qualified_image
        ):
            raise ValueError("Engineering process output/image capability pin differs")
        if self.policy.repository_symbol != self.verifier_spec.job.source.repository_symbol:
            raise ValueError("Engineering process repository pin differs")
        symbols = tuple(row.source_symbol for row in self.policies)
        if len(symbols) != 3 or set(symbols) != {
            "fixture.source.v1",
            "acceptance.fixture.9900",
            "acceptance.fixture.9500",
        }:
            raise ValueError("Engineering process policy set differs")
        return self

    def require_command_spec(self) -> None:
        """The reviewed exact command binds all actual verifier identities and spec bytes."""
        require_command_binding(self.verifier_binding, self.verifier_action, self.command)
        fields = {
            "company_id",
            "task_id",
            "trace_id",
            "actor_id",
            "workspace_id",
            "run_id",
            "action_id",
        }
        if self.verifier_spec.job.model_dump(include=fields) != self.command.model_dump(
            include=fields
        ):
            raise ValueError("Engineering process spec job differs from command")
        if (
            engineering_phase(self.verifier_binding) != "verifier"
            or UUID(self.command.workflow_id) != self.workflow_id
        ):
            raise ValueError("Engineering process workflow identity differs")
        self.verifier_spec.require_policy(self.policy)
        if (
            self.verifier_action.tool,
            self.verifier_action.tool_version,
            self.verifier_action.parameters,
        ) != ("company.builder.run.v1", "v1", self.verifier_spec.model_dump(mode="json")):
            raise ValueError("Engineering process action does not bind exact spec")


def process_config(
    item: PendingEngineeringScenario, command: SegmentCommand, database: str, task_root: Path
) -> EngineeringProcessConfig:
    policies = item.freshness._policies
    assert isinstance(item.runner.publisher, EngineeringArtifactPublisher)
    symbols = ("fixture.source.v1", "acceptance.fixture.9900", "acceptance.fixture.9500")
    return EngineeringProcessConfig(
        catalog=item.catalog,
        declaration=next(iter(item.acceptance.inputs.declarations.values())),
        policy=item.runner.policy,
        capabilities=item.runner.capabilities,
        image_id=item.runner.image_id,
        source_root=item.source.repository,
        source_metadata=item.source.metadata,
        output_target=item.runner.publisher.target,
        proof_target=item.acceptance.proof.target,
        policies=tuple(policies.policy(name) for name in symbols),
        verifier_binding=item.verifier_binding,
        verifier_action=item.verifier_action,
        verifier_spec=item.verifier_spec,
        workflow_id=UUID(command.workflow_id),
        command=command,
        database=database,
        task_root=task_root,
        lease_ttl_seconds=30
        if database.startswith("nexus_company_test_engineering_immediate_")
        else 10,
    )
