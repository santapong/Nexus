"""Actual owner C lifecycle over the stored approved full r2; no implicit approval or worker."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from nexus.company.access import CompanyControlScope
from nexus.company.brain.base import BrainReadScope
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.coding_application_config import CodingApplicationConfig
from nexus.execution.coding_candidate_reader import CodingCandidateReader
from nexus.execution.coding_dispatch import CodingDispatchRecord, dispatch_read
from nexus.execution.coding_lifecycle_bindings import CodingBundle, approved_r2_locked, owner_locked
from nexus.execution.coding_lifecycle_contracts import (
    CodingCandidateReview,
    CodingLifecycleRead,
    CodingLifecycleStatus,
)
from nexus.execution.coding_owner_reads import CodingOwnerReader
from nexus.execution.coding_preparation import PreparedCodingAction, prepare_read
from nexus.execution.coding_services import CodingServices
from nexus.harness.journal_contracts import LedgerScope


class CodingLifecycle:
    """Fixed graph; public selections name Goal/head/action, never actors, paths or allowance."""

    def __init__(
        self, config: CodingApplicationConfig, services: CodingServices, reads: CodingOwnerReader
    ) -> None:
        if (
            type(config) is not CodingApplicationConfig
            or type(services) is not CodingServices
            or type(reads) is not CodingOwnerReader
        ):
            raise ValueError("Coding lifecycle requires its actual configured graph")
        self._owners: list[asyncio.Task[object]] = []
        self._stopped = False
        self.config = config
        self.services = services
        self.reads = reads
        self.factory = services.factory
        self.admission_sha256 = canonical_sha256(config.admission)
        self.candidates = CodingCandidateReader(services, reads)
        self._original = (
            config,
            services,
            reads,
            self.factory,
            canonical_sha256(config),
            self.candidates,
        )
        self.require_composition()

    def require_composition(self) -> None:
        self.services.require_composition()
        self.reads.require_composition()
        self.candidates.require_composition()
        if (
            any(
                a is not z
                for a, z in zip(
                    (self.config, self.services, self.reads, self.factory),
                    self._original[:4],
                    strict=True,
                )
            )
            or canonical_sha256(self.config) != self._original[4]
            or self.candidates is not self._original[5]
            or self.reads.services is not self.services
            or self.services.management.catalog != self.config.catalog
            or self.services.authority.policy != self.config.role_policy
            or self.services.recipe != self.config.recipe
            or self.services.repository_path != self.config.repository_path
            or self.services.repository_selection != self.config.repository_selection
            or self.services.code_sources != self.config.code_sources
            or self.services.prepared_blobs._root != self.config.prepared_root
            or self.services.prepared_blobs.storage_symbol != self.config.prepared_storage_symbol
            or self.services.evidence._root != self.config.planning.storage.model_evidence_root
        ):
            raise ManagementDeniedError("Original coding lifecycle composition changed")

    async def _owned[T](self, value: Awaitable[T], end_us: int) -> T:
        try:
            require_time(end_us)
            if len(self.pending_owners()) >= 32:
                raise ManagementDeniedError("Coding owner pending-resource bound exceeded")
        except BaseException:
            if inspect.iscoroutine(value):
                value.close()
            elif isinstance(value, asyncio.Task):
                self._owners.append(cast(asyncio.Task[object], value))
            raise
        task = asyncio.ensure_future(value)
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        async with asyncio.timeout(max(0, end_us - clock_us()) / 1_000_000):
            result = await asyncio.shield(task)
        require_time(end_us)
        self.require_composition()
        if self._stopped:
            raise ManagementDeniedError("Coding owner admission is stopped")
        return result

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        self._owners[:] = [task for task in self._owners if not task.done() or task.cancelled()]
        return tuple(
            dict.fromkeys(
                (
                    *(task for task in self._owners if not task.done() or task.cancelled()),
                    *self.services.pending_owners(),
                    *self.reads.pending_owners(),
                    *self.candidates.pending_owners(),
                )
            )
        )

    def request_stop(self) -> None:
        self._stopped = True
        self.services.request_stop()
        self.reads.request_stop()
        self.candidates.request_stop()

    def _begin(
        self, scope: CompanyControlScope, owner: AuthenticatedWorkerIdentity, end_us: int
    ) -> int:
        self.require_composition()
        if self._stopped:
            raise ManagementDeniedError("Coding owner admission is stopped")
        admission = self.config.admission
        if type(owner) is not AuthenticatedWorkerIdentity or (
            scope.company_id,
            scope.principal_id,
            owner.identity.principal_id,
            owner.identity.workspace_id,
        ) != (
            admission.company_id,
            admission.procedure.binding.actor_id,
            admission.procedure.binding.actor_id,
            admission.procedure.binding.workspace_id,
        ):
            raise ManagementDeniedError("Coding requires its genuine configured owner")
        before = clock_us()
        now = datetime.now(UTC)
        owner.require_time(now)
        end_us = min(
            end_us,
            before + 30_000_000,
            before + (owner.expires_at - now) // timedelta(microseconds=1),
        )
        require_time(end_us)
        return end_us

    async def _owner_locked_read(
        self, scope: CompanyControlScope, owner: AuthenticatedWorkerIdentity, end: int
    ) -> int:
        async with management_owner_transaction(
            self.factory, scope, owner.identity, allow_paused=True
        ) as (session, control, _):
            end = await owner_locked(self.services, session, control, scope, owner, end)
        require_time(end)
        self.require_composition()
        return end

    async def _bundle_locked_read(
        self, scope: CompanyControlScope, owner: AuthenticatedWorkerIdentity, end: int
    ) -> tuple[CodingBundle, int]:
        async with management_owner_transaction(self.factory, scope, owner.identity) as (
            session,
            control,
            _,
        ):
            value, end = await approved_r2_locked(
                self.services, session, control, scope, owner, end
            )
        require_time(end)
        self.require_composition()
        return value, end

    async def _owner(
        self, scope: CompanyControlScope, owner: AuthenticatedWorkerIdentity, end: int
    ) -> int:
        return await self._owned(self._owner_locked_read(scope, owner, end), end)

    async def _bundle(
        self, scope: CompanyControlScope, owner: AuthenticatedWorkerIdentity, end: int
    ) -> tuple[CodingBundle, int]:
        return await self._owned(self._bundle_locked_read(scope, owner, end), end)

    async def prepare(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        goal: GoalRevisionRef,
        expected_head: UUID,
        *,
        end_us: int,
    ) -> CodingLifecycleRead[PreparedCodingAction]:
        end_us = self._begin(scope, owner, end_us)
        if goal != self.config.goal:
            raise ManagementDeniedError("Coding current Goal differs")
        bundle, end_us = await self._bundle(scope, owner, end_us)
        if bundle.plan.plan_revision_id != expected_head:
            raise ManagementDeniedError("Coding exact r2 head differs")
        actor = bundle.binding.child.binding
        read = await prepare_read(
            self.services,
            LedgerScope(
                company_id=scope.company_id,
                principal_id=actor.actor_id,
                task_id=actor.task_id,
                trace_id=actor.trace_id,
            ),
            end_us=end_us,
        )
        end_us = min(end_us, read.read_end_us)
        final, end_us = await self._bundle(scope, owner, end_us)
        if final.plan != bundle.plan:
            raise ManagementDeniedError("Coding approved r2 changed during preparation")
        return CodingLifecycleRead(read.value, end_us)

    async def dispatch(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        action_id: UUID,
        expected_hash: str,
        *,
        end_us: int,
    ) -> CodingLifecycleRead[CodingDispatchRecord]:
        from nexus.execution.coding_lifecycle_reads import existing_dispatch

        end_us = self._begin(scope, owner, end_us)
        # Issued permanent metadata is checked BEFORE current r2/fresh actor/body/SDK.
        prior, end_us = await self._owned(
            existing_dispatch(self, scope, owner, action_id, expected_hash, end_us), end_us
        )
        if prior is not None:
            return CodingLifecycleRead(prior, await self._owner(scope, owner, end_us))
        bundle, end_us = await self._bundle(scope, owner, end_us)
        actor = bundle.binding.child.binding
        brain = BrainReadScope(
            company_id=scope.company_id,
            workspace_id=actor.workspace_id,
            principal_id=actor.actor_id,
            actor_id=actor.actor_id,
            task_id=actor.task_id,
            task_trace_id=actor.trace_id,
            operation_id=uuid4(),
            trace_id=actor.trace_id,
        )
        read = await dispatch_read(self.services, brain, action_id, expected_hash, end_us=end_us)
        end_us = min(end_us, read.read_end_us)
        final, end_us = await self._bundle(scope, owner, end_us)
        if final.plan != bundle.plan:
            raise ManagementDeniedError("Coding current r2 changed during dispatch")
        return CodingLifecycleRead(read.value, end_us)

    async def status(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        goal_id: UUID,
        *,
        end_us: int,
    ) -> CodingLifecycleRead[CodingLifecycleStatus]:
        from nexus.execution.coding_lifecycle_reads import status

        end_us = self._begin(scope, owner, end_us)
        return await self._owned(status(self, scope, owner, goal_id, end_us), end_us)

    async def candidate(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        action_id: UUID,
        expected_current_revision_id: UUID,
        *,
        end_us: int,
    ) -> CodingLifecycleRead[CodingCandidateReview]:
        return await self.candidates.read(
            scope,
            owner,
            action_id,
            expected_current_revision_id=expected_current_revision_id,
            end_us=self._begin(scope, owner, end_us),
        )

    async def recover_wait(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        action_id: UUID,
        expected_hash: str,
        *,
        expected_goal: GoalRevisionRef,
        expected_current_revision_id: UUID,
        end_us: int,
    ) -> CodingLifecycleRead[PreparedCodingAction]:
        from nexus.execution.coding_preparation_recovery import recover_prepared_wait

        read = await recover_prepared_wait(
            self.services,
            scope,
            owner,
            action_id,
            expected_hash,
            expected_goal=expected_goal,
            expected_current_revision_id=expected_current_revision_id,
            end_us=self._begin(scope, owner, end_us),
            inputs=self.reads,
        )
        return CodingLifecycleRead(read.value, read.read_end_us)
