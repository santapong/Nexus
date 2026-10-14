"""Trusted scheduler dependencies and descriptive native work projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.management.plan_support import CurrentPlanBinding, PlanAdmissionCatalog
from nexus.company.management.plans import RunBinding
from nexus.company.management.scheduling_contracts import ScheduledWork, SchedulerPolicy
from nexus.execution.management_checks import ManagementArtifactFreshness
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import JournalAction


class SchedulerIdentities(Protocol):
    """Configured authenticated actor identities, never constructed from a scan payload."""

    def actor(self, binding: RunBinding) -> VerifiedIdentity:
        """Resolve an already verified identity for this actual approved actor/workspace."""
        ...


class SchedulerResources(Protocol):
    """Configured current DB-only resource revisions; approval snapshots are not a resolver."""

    async def current(
        self,
        session: AsyncSession,
        binding: RunBinding,
        proposal: ActionProposal,
        identity: VerifiedIdentity,
    ) -> tuple[ResourceRevision, ...]:
        """Read bounded actual current conditions under the caller's company mutex."""
        ...


@dataclass(frozen=True)
class SchedulerServices:
    """Process-local trusted providers do not enter DBOS payloads or receipt JSON."""

    policy: SchedulerPolicy
    catalog: PlanAdmissionCatalog
    artifacts: BoundedArtifactReader
    freshness: ManagementArtifactFreshness
    identities: SchedulerIdentities
    resources: SchedulerResources


@dataclass(frozen=True)
class SchedulingCandidate:
    """Internal ORM view; only its strict descriptive projection crosses the service boundary."""

    work: ExecutionWork
    binding: CurrentPlanBinding | None
    projection: ScheduledWork
    action: JournalAction | None = None
    identity: VerifiedIdentity | None = None
    scope: LedgerScope | None = None
