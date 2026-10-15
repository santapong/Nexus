"""Current strategy target/recipient windows retained through the last native DB clock."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.contracts.actions import ApprovalDecision
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactInputs
from nexus.company.management.generated_artifact_privacy import recipients
from nexus.company.management.plan_support import PlanAdmissionCatalog, validate_plan_profile
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.contracts import StrategyCheckInput
from nexus.company.strategy.pair_reader import StrategyNativePair
from nexus.company.strategy.publication_contracts import (
    PreparedStrategyPublication,
    StrategyLoadedPublication,
    StrategyPublicationRules,
)
from nexus.company.strategy.source_inputs import StrategySourceProtection
from nexus.core.llm.company_registry import DataClassification
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import db_now


def strategy_publication_scope(lease: ExecutionLease, action_id: UUID) -> BrainReadScope:
    """Stable S audit IDs, without impersonating an owner or conferring work authority."""
    return BrainReadScope(
        company_id=lease.company_id,
        workspace_id=lease.workspace_id,
        principal_id=lease.actor_id,
        operation_id=uuid5(action_id, "strategy-publication:v1"),
        trace_id=lease.trace_id,
        task_id=lease.task_id,
        task_trace_id=lease.trace_id,
        actor_id=lease.actor_id,
    )


def require_credential(
    credential: AuthenticatedWorkerIdentity,
    identity: VerifiedIdentity,
    scope: BrainReadScope,
    now: datetime,
) -> None:
    """Only a genuine signature-verified process witness can retain credential time."""
    require_acceptance(
        isinstance(credential, AuthenticatedWorkerIdentity)
        and credential.identity == identity
        and (scope.workspace_id, scope.principal_id)
        == (identity.workspace_id, identity.principal_id)
    )
    credential.require_time(now)


@dataclass(frozen=True)
class StrategyReadProtection:
    """Current observations, never a permission DTO or a replacement original snapshot."""

    sources: StrategySourceProtection
    grants: tuple[ResourceGeneration, ...]
    pair: StrategyNativePair
    catalog: PlanAdmissionCatalog

    def require_time(self, now: datetime) -> None:
        self.sources.require_time(now)
        require_acceptance(
            all(row.expires_at is None or row.expires_at > now for row in self.grants)
        )
        validate_plan_profile(self.catalog, self.pair.author_child, now)
        validate_plan_profile(self.catalog, self.pair.verifier_child, now)


@dataclass(frozen=True)
class StrategyPublicationProtection:
    """Exact operation observations; the store still rechecks actual current lease/fence."""

    read: StrategyReadProtection
    lease: ExecutionLease
    approval: ApprovalDecision

    def require_time(self, now: datetime) -> None:
        self.read.require_time(now)
        require_acceptance(
            self.lease.expires_at > now
            and self.approval.issued_at <= now < self.approval.expires_at
        )


async def target_grants_locked(
    session: AsyncSession,
    scope: BrainReadScope,
    prepared: PreparedStrategyPublication,
    rules: StrategyPublicationRules,
) -> tuple[ResourceGeneration, ...]:
    """Complete bounded source/output resource union and each actual target's current readers."""
    targets = tuple(sorted({rules.write.target.resource_id, rules.check.target.resource_id}))
    original = set(prepared.original.snapshot.inputs.required_resource_ids)
    resources = tuple(sorted(original | set(targets)))
    require_acceptance(len(resources) <= 32 and not original.intersection(targets))
    for target_id in targets:
        target = await session.get(BrainResource, (scope.company_id, target_id))
        require_acceptance(target is not None and target.kind == "artifact" and target.active)
    writer = await require_resources(session, scope, resources, await db_now(session))
    values = list(writer)
    for target_id in targets:
        values.extend(await recipients(session, scope, target_id, resources, await db_now(session)))
    require_acceptance(len(values) <= 2080)
    return tuple(values)


@dataclass(frozen=True)
class StrategyProtectedPublication:
    """Actual loaded data plus current windows; no externally accepted permit."""

    publication: StrategyLoadedPublication
    protection: StrategyReadProtection


@dataclass(frozen=True)
class StrategyCheckMaterial:
    """Actual protected command/manifest and the windows the final caller must retain."""

    command: StrategyCheckInput
    inputs: GeneratedArtifactInputs
    classification: DataClassification
    protection: StrategyReadProtection
