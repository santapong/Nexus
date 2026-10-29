"""Concrete registered planning composition and original-operation resource owners."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Event
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contained_query import clock_us
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.context import ContextSelection
from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.brain.retrieval_store import PersistentBrainRetriever
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.planning_authority import ManagementPlanningAuthority
from nexus.company.management.planning_consumer import RegisteredPlanningConsumer
from nexus.company.management.planning_prepared_store import PlanningPreparedStore
from nexus.company.management.scheduling_contracts import WorkflowRegistration
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    NotificationWorkerIdentities,
)
from nexus.core.llm.company_adapter_contracts import EndpointResolver
from nexus.execution.management_services import ManagementExecutionServices
from nexus.execution.model_workflow_identity import application_version
from nexus.execution.runtime_contracts import ExecutionLease, ExecutionSnapshot
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import db_now
from nexus.harness.model_authorizer_contracts import ModelInputRecipe
from nexus.harness.model_evidence import FileModelEvidenceStore
from nexus.harness.model_input_estimator import FullContextInputEstimator

WORKFLOW, VERSION = "company.planning.v1", "v1"
QUEUE, APPLICATION = "nexus.planning", "nexus-planning"
ENTRY_SECONDS, LEASE_SECONDS, CLIENT_SECONDS = 375, 60, 55
REGISTRATION = WorkflowRegistration(
    workflow_name=WORKFLOW, workflow_version=VERSION, queue_name=QUEUE, application_name=APPLICATION
)
APPLICATION_VERSION = application_version(REGISTRATION)


def current(end_us: int) -> None:
    """A caller may shorten an original operation, never replace it after an await."""
    if type(end_us) is not int or not 0 < clock_us() < end_us:
        raise TimeoutError("Original planning operation expired")


async def clock_now(services: PlanningServices) -> datetime:
    """Owned actual DB clock; caller-supplied wall time cannot extend a native lease."""
    async with services.factory() as session:
        return await db_now(session)


async def wait_resources(owners: tuple[asyncio.Future[object], ...], end: float) -> None:
    """Wait for actual resources without cancelling them on a caller stop or elapsed end."""
    if owners:
        await asyncio.wait(owners, timeout=max(0, end - asyncio.get_running_loop().time()))


@dataclass(frozen=True)
class PlanningServices:
    """Explicit server choices; neither HTTP nor model content can select authority or caps."""

    factory: async_sessionmaker[AsyncSession]
    management: ManagementExecutionServices
    contexts: PersistentContextAssembler
    prepared: PlanningPreparedStore
    estimator: FullContextInputEstimator
    recipe: ModelInputRecipe
    identities: NotificationWorkerIdentities
    resolver: EndpointResolver
    evidence: FileModelEvidenceStore
    worker_id: UUID
    registry_id: str
    max_output_tokens: int
    selection: ContextSelection
    execution: ExecutionStore = field(init=False)
    authority: ManagementPlanningAuthority = field(init=False)
    _bound: tuple[object, ...] = field(init=False, repr=False)
    _operations: dict[str, PlanningOperation] = field(default_factory=dict, init=False, repr=False)
    _stopping: Event = field(default_factory=Event, init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.management) is not ManagementExecutionServices
            or type(self.contexts) is not PersistentContextAssembler
            or type(self.contexts._retriever) is not PersistentBrainRetriever
            or type(self.contexts._retriever.blobs) is not ProtectedBlobStore
            or type(self.contexts._authority) is not ManagementPlanningAuthority
            or type(self.prepared) is not PlanningPreparedStore
            or type(self.estimator) is not FullContextInputEstimator
            or type(self.identities) is not NotificationWorkerIdentities
            or type(self.evidence) is not FileModelEvidenceStore
            or type(self.max_output_tokens) is not int
        ):
            raise ValueError("Planning needs its concrete native/context/evidence composition")
        object.__setattr__(
            self, "recipe", ModelInputRecipe.model_validate_json(self.recipe.model_dump_json())
        )
        object.__setattr__(
            self,
            "selection",
            ContextSelection.model_validate_json(self.selection.model_dump_json()),
        )
        row = next(
            (
                value
                for value in self.management.catalog.models.models
                if value.registry_id == self.registry_id
            ),
            None,
        )
        authority = self.contexts._authority
        assert type(authority) is ManagementPlanningAuthority
        object.__setattr__(self, "authority", authority)
        if (
            row is None
            or not 0 < self.max_output_tokens <= row.max_output_tokens
            or self.selection.company_id != self.management.catalog.company_id
            or authority.management is not self.management
            or authority.recipe != self.recipe
            or (authority.policy.workflow_name, authority.policy.workflow_version)
            != (WORKFLOW, VERSION)
            or self.prepared.factory is not self.factory
            or self.prepared.recipe != self.recipe
            or self.prepared.sources.artifacts is not self.management.artifacts
            or self.prepared.sources.freshness is not self.management.freshness
            or self.contexts._factory is not self.factory
            or self.contexts._retriever.factory is not self.factory
            or self.contexts._retriever.blobs is not self.management.artifacts.blobs
        ):
            raise ValueError("Planning dependencies or fixed server model configuration differ")
        object.__setattr__(self, "execution", self.management.execution_store(self.factory))
        object.__setattr__(self, "_bound", self._pins())

    def _pins(self) -> tuple[object, ...]:
        return (
            self.factory,
            self.management,
            self.contexts,
            self.prepared,
            self.estimator,
            self.identities,
            self.resolver,
            self.evidence,
            self.execution,
            self.contexts._authority,
            self.contexts._retriever,
            canonical_sha256(self.management.catalog),
            canonical_sha256(self.recipe),
            canonical_sha256(self.selection),
            self.worker_id,
            self.registry_id,
            self.max_output_tokens,
            self.evidence._root,
        )

    def require_composition(self) -> None:
        actual = self._pins()
        if (
            any(a is not b for a, b in zip(actual[:11], self._bound[:11], strict=True))
            or actual[11:] != self._bound[11:]
            or self.execution._factory is not self.factory
            or self.prepared.factory is not self.factory
            or self.contexts._factory is not self.factory
            or self.contexts._retriever.factory is not self.factory
            or self.contexts._retriever.blobs is not self.management.artifacts.blobs
            or self.authority is not self.contexts._authority
        ):
            raise ValueError("Original planning composition changed")
        self.authority._require_original()
        self.prepared._composition()

    def require_accepting(self) -> None:
        self.require_composition()
        if self._stopping.is_set():
            raise ValueError("Planning admission is stopped")

    def request_stop(self) -> None:
        """Stop orchestration once; actual SDK/native/file leaves remain strongly owned."""
        self._stopping.set()
        for operation in tuple(self._operations.values()):
            operation.request_stop()

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        return tuple(
            dict.fromkeys(
                (
                    *self.prepared.pending_owners(),
                    *self.evidence.pending_owners(),
                    *self.prepared.blobs.pending_owners(),
                    *cast(ProtectedBlobStore, self.contexts._retriever.blobs).pending_owners(),
                    *(
                        task
                        for value in tuple(self._operations.values())
                        for task in value.pending_owners()
                    ),
                )
            )
        )


class PlanningOperation:
    """Actual lease/tasks/consumer remain reachable after denied or interrupted delivery."""

    running: bool

    def __init__(self, services: PlanningServices, key: str, end_us: int) -> None:
        services.require_accepting()
        current(end_us)
        if services.pending_owners() or any(
            value.running for value in services._operations.values()
        ):
            raise ValueError("Planning retains an unfinished original operation")
        driver = asyncio.current_task()
        if driver is None:
            raise ValueError("Planning needs the actual orchestration task")
        self.services, self.key, self.driver = services, key, driver
        self.end = min(end_us, clock_us() + ENTRY_SECONDS * 1_000_000)
        self.owners: list[asyncio.Task[object]] = []
        self.credential: AuthenticatedWorkerIdentity | None = None
        self.lease_task: asyncio.Task[ExecutionLease] | None = None
        self.waiting_task: asyncio.Task[ExecutionSnapshot] | None = None
        self.lease: ExecutionLease | None = None
        self.consumer: RegisteredPlanningConsumer | None = None
        self.first: BaseException | None = None
        self.released, self.running, self._stop_sent = False, True, False
        services._operations[key] = self

    def request_stop(self) -> None:
        if self.consumer is not None:
            self.consumer.request_stop()
        if not self._stop_sent and self.running and not self.driver.done():
            self._stop_sent = True
            self.driver.get_loop().call_soon_threadsafe(self.driver.cancel, "Planning stopping")

    def require_current(self) -> None:
        current(self.end)
        self.services.require_composition()

    def require_admission(self) -> None:
        self.require_current()
        self.services.require_accepting()
        if self.first is not None or self._stop_sent:
            raise ValueError("Original planning caller stopped admission")

    def shorten(self, now: datetime, before_us: int, deadlines: tuple[datetime, ...]) -> None:
        """Carry the actual clock's original windows through transaction exit and later IO."""
        self.end = min(
            (
                self.end,
                *(before_us + (value - now) // timedelta(microseconds=1) for value in deadlines),
            )
        )
        self.require_current()

    async def call[T](self, value: Awaitable[T], *, end_us: int | None = None) -> T:
        limit = min(self.end, end_us if end_us is not None else self.end)
        try:
            current(limit)
            self.services.require_composition()
        except BaseException:
            if inspect.iscoroutine(value):
                value.close()
            elif isinstance(value, asyncio.Task):
                self.owners.append(cast(asyncio.Task[object], value))
            raise
        task = asyncio.ensure_future(value)
        self.owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            async with asyncio.timeout(max(0, limit - clock_us()) / 1_000_000):
                result = await asyncio.shield(task)
        except BaseException as first:
            self.first = self.first or first
            if self.consumer is not None:
                self.consumer.request_stop()
            raise
        current(limit)
        self.services.require_composition()
        return result

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        return tuple(
            dict.fromkeys(
                (
                    *(task for task in self.owners if not task.done() or task.cancelled()),
                    *(self.consumer.pending_owners() if self.consumer is not None else ()),
                    *self.services.prepared.pending_owners(),
                    *self.services.evidence.pending_owners(),
                    *self.services.prepared.blobs.pending_owners(),
                    *cast(
                        ProtectedBlobStore, self.services.contexts._retriever.blobs
                    ).pending_owners(),
                )
            )
        )

    async def retire(self) -> None:
        """Resource-only completion; no renewed lease, later candidate or expired-end SQL."""
        while self.pending_owners() and clock_us() < self.end:
            if any(task.cancelled() for task in self.pending_owners()):
                return  # A cancelled wrapper cannot prove its underlying resource settled.
            try:
                await wait_resources(
                    self.pending_owners(),
                    asyncio.get_running_loop().time() + max(0, self.end - clock_us()) / 1_000_000,
                )
            except asyncio.CancelledError as first:
                self.first = self.first or first
        if self.pending_owners():
            return
        if (
            self.lease_task is not None
            and self.lease_task.done()
            and not self.lease_task.cancelled()
            and self.lease_task.exception() is None
        ):
            self.lease = self.lease_task.result()  # Actual resource handle, never new execution.
        if (
            self.waiting_task is not None
            and self.waiting_task.done()
            and not self.waiting_task.cancelled()
            and self.waiting_task.exception() is None
        ):
            self.released = self.waiting_task.result().worker_id is None
        if self.lease is not None and self.credential is not None and not self.released:
            self.require_current()
            now = await self.call(clock_now(self.services))
            self.credential.require_time(now)
            if self.lease.expires_at <= now:
                raise ValueError("Original planning lease expired before resource release")
            await self.call(
                self.services.execution.release(
                    self.lease,
                    self.credential.identity,
                    blocked=self.first is not None,
                )
            )
            self.released = True

    def finish(self) -> None:
        self.running = False
        if not self.pending_owners():
            self.services._operations.pop(self.key, None)
        if self.first is not None:
            self.first.__dict__["_nexus_planning_pending"] = self.pending_owners()
            self.first.__dict__["_nexus_planning_operation"] = self
