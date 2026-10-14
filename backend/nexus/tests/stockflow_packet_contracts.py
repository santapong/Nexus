"""Strict prepared test state and hash-checked read projection contain no execution permission."""

from pydantic import BaseModel, ConfigDict

from nexus.builder.contracts import BuilderCapabilities, BuilderValue
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.policy import BuilderToolPolicy
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.execution.runtime_contracts import ExecutionLease


class PreparedState(BuilderValue):
    scope: str
    spec: BuilderExecutionSpec
    action: ActionProposal
    policy: BuilderToolPolicy
    catalog: PlanAdmissionCatalog
    capabilities: BuilderCapabilities
    metadata: ArtifactRevisionRef
    released_lease: ExecutionLease
    source_policy: SourcePolicy
    source_repository: str


class ReviewPacket(BaseModel):
    # Other packet fields are descriptive; the caller must verify the complete bytes first.
    model_config = ConfigDict(frozen=True, extra="ignore")
    scope: str
    source_event: str
    state_sha256: str
    action_sha256: str
    actual_argv: tuple[str, ...]
