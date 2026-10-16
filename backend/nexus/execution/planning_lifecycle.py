"""Explicit owner lifecycle over native planning; no implicit approval or model activation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from nexus.company.access import CompanyControlScope
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.lifecycle import PlanRevision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.company.management.planning_proposal_bridge import PlanningProposalBridge
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.planning_application_config import (
    PlanningApplicationConfig,
    PlanningSourcePolicies,
)
from nexus.execution.planning_dispatch import PlanningDispatchRecord
from nexus.execution.planning_dispatch import dispatch as dispatch_action
from nexus.execution.planning_lifecycle_bindings import (
    PlanningBundle,
    approved_bundle,
    owner_locked,
)
from nexus.execution.planning_lifecycle_contracts import (
    PlanningCandidateReview,
    PlanningLifecycleRead,
    PlanningLifecycleStatus,
)
from nexus.execution.planning_preparation import PreparedPlanningAction, prepare_work
from nexus.execution.planning_services import PlanningServices
from nexus.harness.journal_contracts import LedgerScope


class PlanningLifecycle:
    """One fixed configured goal and shared runtime; native rows supply every base plan.

    Cohesion exception: this >300-line class keeps seven explicit operations on
    the same sealed graph and original owner/source cutoff, without mutable callbacks.
    """

    def __init__(self, config: PlanningApplicationConfig, services: PlanningServices) -> None:
        if type(config) is not PlanningApplicationConfig or type(services) is not PlanningServices:
            raise ValueError("Planning lifecycle requires concrete configured services")
        self.config = PlanningApplicationConfig.model_validate_json(
            config.model_dump_json(by_alias=True)
        )
        self.services, self.factory = services, services.factory
        self._bundles: list[PlanningBundle] = []
        self._original = (self.config, services, services.factory, canonical_sha256(self.config))
        self.require_composition()

    def require_composition(self) -> None:
        services, config = self.services, self.config
        services.require_composition()
        freshness = services.management.freshness
        if type(services.management.artifacts.blobs) is not ProtectedBlobStore:
            raise ValueError("Planning lifecycle needs its concrete protected Brain storage")
        brain = services.management.artifacts.blobs
        if (
            (
                config is not self._original[0]
                or services is not self._original[1]
                or self.factory is not self._original[2]
                or services.factory is not self.factory
                or canonical_sha256(config) != self._original[3]
            )
            or canonical_sha256(services.management.catalog) != canonical_sha256(config.catalog)
            or services.authority.policy != config.role_policy
            or services.recipe != config.recipe
            or services.selection != config.selection
            or (services.registry_id, services.max_output_tokens, services.worker_id)
            != (config.registry_id, config.max_output_tokens, config.worker_id)
            or type(freshness) is not RegisteredSourceFreshness
            or freshness._factory is not self.factory
            or type(freshness._policies) is not PlanningSourcePolicies
            or freshness._policies.policies != config.source_policies
            or (brain._root, services.prepared.blobs._root, services.evidence._root)
            != (
                config.storage.brain_root,
                config.storage.prepared_root,
                config.storage.model_evidence_root,
            )
            or (brain.storage_symbol, services.prepared.blobs.storage_symbol)
            != (config.storage.brain_storage_symbol, config.storage.prepared_storage_symbol)
        ):
            raise ValueError("Original planning lifecycle/config/source composition changed")
        for bundle in self._bundles:
            bundle.require_composition()

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        """Actual runtime/SDK/FS leaves remain reachable after an interrupted owner request."""
        return tuple(
            dict.fromkeys(
                (
                    *self.services.pending_owners(),
                    *(
                        cast(asyncio.Task[object], task)
                        for bundle in self._bundles
                        for task in bundle.reader.pending_owners()
                    ),
                )
            )
        )

    def request_stop(self) -> None:
        self.services.request_stop()

    def _begin(
        self, scope: CompanyControlScope, owner: AuthenticatedWorkerIdentity, end_us: int
    ) -> int:
        self.require_composition()
        if type(end_us) is not int or end_us <= 0:
            raise ValueError("Planning operation requires its finite original end")
        if (
            type(owner) is not AuthenticatedWorkerIdentity
            or scope.company_id != self.config.admission.company_id
            or (scope.principal_id, owner.identity.principal_id, owner.identity.workspace_id)
            != (
                self.config.admission.procedure.binding.actor_id,
                self.config.admission.procedure.binding.actor_id,
                self.config.admission.procedure.binding.workspace_id,
            )
        ):
            raise ManagementDeniedError("Planning requires its genuine configured owner witness")
        before, now = clock_us(), datetime.now(UTC)
        owner.require_time(now)
        end_us = min(
            end_us,
            before + 30_000_000,
            before + (owner.expires_at - now) // timedelta(microseconds=1),
        )
        require_time(end_us)
        return end_us

    async def _owner(
        self, scope: CompanyControlScope, owner: AuthenticatedWorkerIdentity, end_us: int
    ) -> int:
        async with asyncio.timeout(max(0, end_us - clock_us()) / 1_000_000):
            async with management_owner_transaction(
                self.factory, scope, owner.identity, allow_paused=True
            ) as (session, control, _):
                end_us = await owner_locked(
                    self.services, self.config, session, control, scope, owner, end_us
                )
        self.require_composition()
        require_time(end_us)
        return end_us

    async def _bundle(
        self, scope: CompanyControlScope, owner: AuthenticatedWorkerIdentity, end_us: int
    ) -> tuple[PlanningBundle, int]:
        async with asyncio.timeout(max(0, end_us - clock_us()) / 1_000_000):
            async with management_owner_transaction(
                self.factory, scope, owner.identity, allow_paused=True
            ) as (session, control, _):
                end_us = await owner_locked(
                    self.services, self.config, session, control, scope, owner, end_us
                )
                bundle = await approved_bundle(session, control, self.config, self.services)
        self._bundles[:] = [item for item in self._bundles if item.reader.pending_owners()]
        if len(self._bundles) >= 32:
            raise ManagementDeniedError("Planning retains too many actual protected reads")
        self._bundles.append(bundle)
        self.require_composition()
        require_time(end_us)
        return bundle, end_us

    def _goal(self, goal: GoalRevisionRef) -> None:
        if goal != self.config.goal:
            raise ManagementDeniedError(
                "Planning goal differs from its exact configured native revision"
            )

    async def bootstrap(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        goal: GoalRevisionRef,
        expected_head: UUID | None,
        *,
        end_us: int,
    ) -> PlanningLifecycleRead[PlanRevision]:
        """Propose only the server r1; this does not approve, register, claim or enqueue."""
        end_us = self._begin(scope, owner, end_us)
        self._goal(goal)
        self.services.require_accepting()
        end_us = await self._owner(scope, owner, end_us)
        plans = ManagementPlanStore(
            self.factory,
            self.services.management.catalog,
            source_freshness=self.services.management.freshness,
        )
        value = await plans.propose(
            scope,
            owner.identity,
            self.config.admission.payload("planning"),
            expected_current_revision_id=expected_head,
            credential=owner,
            end_us=end_us,
        )
        end_us = await self._owner(scope, owner, end_us)
        return PlanningLifecycleRead(value, end_us)

    async def prepare(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        goal: GoalRevisionRef,
        expected_head: UUID | None,
        *,
        end_us: int,
    ) -> PlanningLifecycleRead[PreparedPlanningAction]:
        """The genuine actor prepares; never borrow owner credentials or recover implicitly."""
        end_us = self._begin(scope, owner, end_us)
        self._goal(goal)
        bundle, end_us = await self._bundle(scope, owner, end_us)
        if (
            expected_head != bundle.base.plan_revision_id
            or bundle.head_revision_id != expected_head
        ):
            raise ManagementDeniedError(
                "Planning preparation requires its original approved r1 CAS"
            )
        actor = bundle.base.payload.children[0].binding
        value = await prepare_work(
            self.services,
            LedgerScope(
                company_id=scope.company_id,
                principal_id=actor.actor_id,
                task_id=actor.task_id,
                trace_id=actor.trace_id,
            ),
            end_us=end_us,
        )
        end_us = await self._owner(scope, owner, end_us)
        return PlanningLifecycleRead(value, end_us)

    async def dispatch(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        action_id: UUID,
        expected_hash: str,
        *,
        end_us: int,
    ) -> PlanningLifecycleRead[PlanningDispatchRecord]:
        """Owner trigger and genuine actor dispatch; known metadata needs no new actor JWT."""
        from nexus.execution.planning_lifecycle_reads import existing_dispatch

        end_us = self._begin(scope, owner, end_us)
        bundle, end_us = await self._bundle(scope, owner, end_us)
        value, end_us = await existing_dispatch(
            self, scope, owner, action_id, expected_hash, end_us
        )
        if value is None:
            actor = bundle.base.payload.children[0].binding
            brain = BrainReadScope(
                company_id=scope.company_id,
                workspace_id=actor.workspace_id,
                principal_id=actor.actor_id,
                operation_id=uuid4(),
                trace_id=actor.trace_id,
                task_id=actor.task_id,
                task_trace_id=actor.trace_id,
                actor_id=actor.actor_id,
            )
            value = await dispatch_action(
                self.services, brain, action_id, expected_hash, end_us=end_us
            )
        end_us = await self._owner(scope, owner, end_us)
        return PlanningLifecycleRead(value, end_us)

    async def status(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        goal_id: UUID,
        *,
        end_us: int,
    ) -> PlanningLifecycleRead[PlanningLifecycleStatus]:
        from nexus.execution.planning_lifecycle_reads import status

        end_us = self._begin(scope, owner, end_us)
        return await status(self, scope, owner, goal_id, end_us)

    async def candidate(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        action_id: UUID,
        expected_head: UUID,
        *,
        end_us: int,
    ) -> PlanningLifecycleRead[PlanningCandidateReview]:
        from nexus.execution.planning_lifecycle_reads import candidate

        end_us = self._begin(scope, owner, end_us)
        return await candidate(self, scope, owner, action_id, expected_head, end_us)

    async def propose(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        action_id: UUID,
        goal: GoalRevisionRef,
        expected_head: UUID,
        *,
        end_us: int,
    ) -> PlanningLifecycleRead[PlanRevision]:
        from nexus.execution.planning_lifecycle_reads import replay_target

        end_us = self._begin(scope, owner, end_us)
        self._goal(goal)
        self.services.require_accepting()
        bundle, end_us = await self._bundle(scope, owner, end_us)
        if expected_head not in {bundle.base.plan_revision_id, bundle.head_revision_id}:
            raise ManagementDeniedError("Planning proposal expected head differs")
        value, end_us = await replay_target(self, bundle, scope, owner, action_id, end_us)
        if value is None:
            value = await PlanningProposalBridge(bundle.plans, bundle.reader).propose(
                scope,
                owner.identity,
                action_id,
                expected_goal=goal,
                expected_current_revision_id=expected_head,
                end_us=end_us,
                credential=owner,
            )
        bundle.require_composition()
        end_us = await self._owner(scope, owner, end_us)
        return PlanningLifecycleRead(value, end_us)

    async def approve(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        revision_id: UUID,
        exact_hash: str,
        expected_head: UUID | None,
        *,
        end_us: int,
    ) -> PlanningLifecycleRead[PlanRevision]:
        from nexus.execution.planning_lifecycle_reads import approval_store

        end_us = self._begin(scope, owner, end_us)
        self.services.require_accepting()
        plans, end_us = await approval_store(self, scope, owner, revision_id, exact_hash, end_us)
        value = await plans.approve_and_register(
            scope,
            owner.identity,
            revision_id,
            exact_hash,
            expected_current_revision_id=expected_head,
            credential=owner,
            end_us=end_us,
        )
        end_us = await self._owner(scope, owner, end_us)
        return PlanningLifecycleRead(value, end_us)

    async def recover_wait(
        self,
        scope: CompanyControlScope,
        owner: AuthenticatedWorkerIdentity,
        action_id: UUID,
        expected_hash: str,
        *,
        expected_goal: GoalRevisionRef,
        expected_head: UUID,
        end_us: int,
    ) -> PlanningLifecycleRead[PreparedPlanningAction]:
        """Only an explicit recovery call delegates the closed native unissued-wait transition."""
        from nexus.execution.planning_preparation_recovery import recover_prepared_wait

        end_us = self._begin(scope, owner, end_us)
        self._goal(expected_goal)
        _, end_us = await self._bundle(scope, owner, end_us)
        value = await recover_prepared_wait(
            self.services,
            scope,
            owner,
            action_id,
            expected_hash,
            expected_goal=expected_goal,
            expected_current_revision_id=expected_head,
            end_us=end_us,
        )
        end_us = await self._owner(scope, owner, min(end_us, value.read_end_us))
        return PlanningLifecycleRead(value.value, end_us)
