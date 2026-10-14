"""Pending verifier fixture carries approved inputs, no invented verifier output or lease."""

from dataclasses import dataclass

from nexus.builder.engineering_acceptance import EngineeringWorkAcceptanceStore
from nexus.builder.engineering_runner import EngineeringNativeBuilderRunner
from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.source_guard import RegisteredBuilderSource
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.plans import RunBinding


@dataclass(frozen=True)
class PendingEngineeringScenario:
    """Author has actual native output; verifier is authorized and permanently dispatched only."""

    acceptance: EngineeringWorkAcceptanceStore
    runner: EngineeringNativeBuilderRunner
    author: BuilderRunResult
    catalog: PlanAdmissionCatalog
    verifier_binding: RunBinding
    verifier_action: ActionProposal
    verifier_spec: BuilderExecutionSpec
    source: RegisteredBuilderSource
    artifacts: BoundedArtifactReader
    freshness: RegisteredSourceFreshness
