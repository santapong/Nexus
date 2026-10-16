"""Process-configured native compiler/actor/services; no dependencies in portable commands."""

import asyncio
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.management.acceptance_recovery import AcceptanceRecovery
from nexus.company.management.acceptance_store import WorkAcceptanceStore
from nexus.company.management.base import Symbol
from nexus.company.management.generated_artifact_store import GeneratedArtifactPublisher
from nexus.company.management.native_report_producer import NativeReportProducer
from nexus.company.management.plans import RunBinding
from nexus.company.management.report_artifact_reader import ReportArtifactReader
from nexus.company.management.report_inputs import PersistentReportInputLoader
from nexus.company.management.scheduling_contracts import WorkflowRegistration
from nexus.company.management.scheduling_support import SchedulerIdentities, SchedulerResources
from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
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

    report_credentials: tuple[tuple[RunBinding, NotificationWorkerIdentities], ...] = ()
    _nexus_owners: list[asyncio.Task[object]] = field(
        default_factory=list, init=False, repr=False, compare=False
    )

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        owners = list(self._nexus_owners)
        for store in (self.publisher.blobs, self.artifacts.blobs):
            if isinstance(store, ProtectedBlobStore):
                owners.extend(store.pending_owners())
        return tuple(dict.fromkeys(task for task in owners if not task.done() or task.cancelled()))

    def __post_init__(self) -> None:
        if self.publisher.catalog.nexus_cycle_admission is not None and (
            type(self.publisher.blobs) is not ProtectedBlobStore
            or self.artifacts.blobs is not self.publisher.blobs
            or type(self.producer.inputs) is not PersistentReportInputLoader
            or type(self.producer.inputs.reader) is not ReportArtifactReader
            or self.producer.inputs.reader.artifacts is not self.artifacts
            or type(self.producer.inputs.reader.retriever) is not PersistentBrainRetriever
            or self.producer.inputs.reader.retriever.blobs is not self.publisher.blobs
            or self.producer.inputs.reader.retriever.factory is not self.factory
            or self.producer.inputs.factory is not self.factory
        ):
            raise ValueError("Nexus report needs one concrete owned protected IO graph")
        if self.report_credentials:
            admission = self.publisher.catalog.nexus_cycle_admission
            if (
                admission is None
                or len(self.report_credentials) != 2
                or tuple(binding for binding, _ in self.report_credentials)
                != tuple(slot.child.binding for slot in admission.slots[3:5])
                or any(
                    type(source) is not NotificationWorkerIdentities
                    for _, source in self.report_credentials
                )
            ):
                raise ValueError(
                    "Nexus report credentials must map the exact two configured actors"
                )

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
