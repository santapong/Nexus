"""Trusted fixed engineering runtime services remain outside portable workflow payloads."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.engineering_acceptance import EngineeringWorkAcceptanceStore
from nexus.builder.engineering_acceptance_recovery import EngineeringAcceptanceRecovery
from nexus.builder.engineering_runner import EngineeringNativeBuilderRunner
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.plans import RunBinding
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.engineering_worker_identity import EngineeringWorkerIdentities
from nexus.execution.runtime_contracts import ExecutionLease


class EngineeringSourceResolver(Protocol):
    """Server configuration maps the actual approved source; callers cannot choose a path."""

    def resolve(
        self,
        binding: RunBinding,
        spec: BuilderExecutionSpec,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
    ) -> BuilderSourceGuard: ...


class EngineeringWorkerHook(Protocol):
    """Process test/observation hooks convey phases, never permission or acceptance."""

    async def __call__(self, phase: str, command: SegmentCommand) -> None: ...


@dataclass(frozen=True)
class EngineeringWorkerServices:
    """Fixed live dependencies must be reconstructed after an OS process restart."""

    factory: async_sessionmaker[AsyncSession]
    catalog: PlanAdmissionCatalog
    runner: EngineeringNativeBuilderRunner
    acceptance: EngineeringWorkAcceptanceStore
    recovery: EngineeringAcceptanceRecovery
    identities: EngineeringWorkerIdentities
    sources: EngineeringSourceResolver
    worker_id: UUID
    lease_ttl_seconds: int = 60
    hook: EngineeringWorkerHook | None = None

    async def observe(self, phase: str, command: SegmentCommand) -> None:
        """Emit an optional trusted checkpoint observation without writing native authority."""
        if self.hook is not None:
            await self.hook(phase, command)
