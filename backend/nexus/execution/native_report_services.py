"""Process-configured native compiler/actor/services; no dependencies in portable commands."""

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.management.acceptance_recovery import AcceptanceRecovery
from nexus.company.management.acceptance_store import WorkAcceptanceStore
from nexus.company.management.base import Symbol
from nexus.company.management.generated_artifact_store import GeneratedArtifactPublisher
from nexus.company.management.native_report_producer import NativeReportProducer
from nexus.company.management.scheduling_contracts import WorkflowRegistration
from nexus.company.management.scheduling_support import SchedulerIdentities, SchedulerResources
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_store import ExecutionStore

NATIVE_WORKFLOW = "internal.report"
NATIVE_VERSION = "v1"
NATIVE_QUEUE = "nexus.management.native"
NATIVE_APPLICATION = "nexus-native-management"
NativePhase = Literal[
    "intent_committed", "artifact_published", "receipt_recorded", "acceptance_recorded"
]


class NativeReportHook(Protocol):
    """Trusted process test/observability hook; never an authority parameter."""

    async def __call__(self, phase: NativePhase, command: SegmentCommand) -> None: ...


@dataclass(frozen=True)
class NativeReportServices:
    """Use configured verified actors and full management stores, never manufacture owner scope."""

    factory: async_sessionmaker[AsyncSession]
    execution: ExecutionStore
    effects: EffectStore
    producer: NativeReportProducer
    publisher: GeneratedArtifactPublisher
    acceptance: WorkAcceptanceStore
    recovery: AcceptanceRecovery
    artifacts: BoundedArtifactReader
    identities: SchedulerIdentities
    resources: SchedulerResources
    registration: WorkflowRegistration
    worker_id: UUID
    lease_ttl_seconds: int = 60
    hook: NativeReportHook | None = None
    executor_id: str = "nexus-native-management-v1-local"

    def __post_init__(self) -> None:
        if TypeAdapter(Symbol).validate_python(self.executor_id) != self.executor_id:
            raise ValueError("Native executor identity must be a stable configured symbol")
        if (
            self.registration.workflow_name != NATIVE_WORKFLOW
            or self.registration.workflow_version != NATIVE_VERSION
        ):
            raise ValueError("Native worker workflow/version is not registered")
        if (
            self.registration.queue_name != NATIVE_QUEUE
            or self.registration.application_name != NATIVE_APPLICATION
        ):
            raise ValueError("Native worker queue/application is not registered")
        if type(self.lease_ttl_seconds) is not int or not 1 <= self.lease_ttl_seconds <= 300:
            raise ValueError("Native worker lease duration is unregistered")

    async def observe(self, phase: NativePhase, command: SegmentCommand) -> None:
        """Observe an actual native boundary without changing authority or counters."""
        if self.hook is not None:
            await self.hook(phase, command)
