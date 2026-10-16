"""Explicit owner-triggered recovery of one protected, wholly unissued planning wait."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.management.action_review_planning import (
    PlanningReviewInputs,
    PlanningReviewSelection,
)
from nexus.company.management.action_review_resources import (
    action_resource_symbols,
    review_named_artifacts,
)
from nexus.company.management.action_review_store import review_disclosure
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.nexus_coding_catalog import configured_nexus_admission
from nexus.company.management.owner_view_sources import owner_brain_scope
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.planning_prepared_contracts import StoredPlanningRequest
from nexus.company.management.plans import RunBinding
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.core.llm.company_pricing import CostQuote
from nexus.execution.planning_context import quote_locked, state_locked
from nexus.execution.planning_preparation import PreparedPlanningAction
from nexus.execution.planning_services import PlanningOperation, PlanningServices
from nexus.execution.runtime_approval_recovery import (
    recovery_ledger,
    recovery_scope,
    require_unissued_pending,
)
from nexus.execution.runtime_contracts import ExecutionSnapshot
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now, execution_row, runtime_transaction, snapshot
from nexus.harness.journal_contracts import ActionRecord, LedgerScope
from nexus.harness.journal_models import CompanyControl


@dataclass(frozen=True, slots=True)
class RecoveredPlanningWait:
    """An exact saved action and original read cutoff; never an effect permission."""

    value: PreparedPlanningAction
    read_end_us: int


def _planner(services: PlanningServices, goal: GoalRevisionRef) -> RunBinding:
    admission = configured_nexus_admission(services.management.catalog)
    if admission is None or admission.goal != goal:
        raise ValueError("Recovery requires the exact configured Nexus planning goal")
    return admission.slots[0].child.binding


def _settled(operation: PlanningOperation) -> None:
    services = operation.services
    leaves = (
        *services.prepared.pending_owners(),
        *services.prepared.blobs.pending_owners(),
        *services.evidence.pending_owners(),
        *cast(ProtectedBlobStore, services.contexts._retriever.blobs).pending_owners(),
    )
    if leaves or any(
        value is not operation and (value.running or value.pending_owners())
        for value in services._operations.values()
    ):
        raise ValueError("Original planning graph still owns unresolved resources")


async def _binding(
    operation: PlanningOperation,
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    goal: GoalRevisionRef,
    head: UUID,
) -> CurrentPlanBinding:
    assert scope.task_id is not None
    state = await state_locked(operation, session, control, scope)
    current = await ManagementPlanStore.current_binding(session, scope.company_id, scope.task_id)
    admission = configured_nexus_admission(operation.services.management.catalog)
    if (
        current is None
        or admission is None
        or current.plan.revision != 1
        or current.child != admission.slots[0].child
        or (state.goal, state.plan_id, state.head) != (goal, admission.plan_id, head)
        or current.plan.plan_revision_id != head
    ):
        raise ValueError("Recovery requires the unchanged approved Nexus r1 and exact goal/head")
    return current


async def _static(
    operation: PlanningOperation,
    session: AsyncSession,
    control: CompanyControl,
    owner_scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    actor: AuthenticatedWorkerIdentity,
    binding: CurrentPlanBinding,
    action: ActionRecord,
) -> None:
    services = operation.services
    await require_brain_scope(
        session, control, owner_brain_scope(owner_scope, owner.identity), owner.identity, owner=True
    )
    if owner.identity.principal_id != control.owner_id:
        raise ValueError("Recovery requires the actual current owner")
    symbols = await action_resource_symbols(
        session, binding, action.proposal, services.management.catalog
    )
    refs, ids = await review_named_artifacts(
        session, binding, action.proposal, services.management.catalog, symbols
    )
    actor_scope = CompanyControlScope(
        company_id=control.company_id,
        principal_id=actor.identity.principal_id,
        operation_id=owner_scope.operation_id,
        trace_id=owner_scope.trace_id,
    )
    deadlines = [owner.expires_at, actor.expires_at]
    if action.approval is not None:
        deadlines.append(action.approval.expires_at)
    for scope, witness in ((owner_scope, owner), (actor_scope, actor)):
        disclosure = await review_disclosure(
            session, control, scope, witness.identity, services.prepared.sources, refs, ids
        )
        if disclosure is None:
            raise ValueError("Original owner/actor static source READ is unavailable")
        if disclosure.valid_until is not None:
            deadlines.append(disclosure.valid_until)
    from nexus.builder.contained_query import clock_us

    before = clock_us()
    now = await db_now(session)
    owner.require_time(now)
    actor.require_time(now)
    operation.shorten(now, before, tuple(deadlines))


@dataclass(frozen=True, slots=True)
class PreparedWaitRecovery:
    """Concrete original native/source/credential composition; never accepted from a request."""

    operation: PlanningOperation
    owner_scope: CompanyControlScope
    owner: AuthenticatedWorkerIdentity
    actor: AuthenticatedWorkerIdentity
    brain: BrainReadScope
    initial: ExecutionSnapshot
    action: ActionRecord
    selected: PlanningReviewSelection
    loaded: StoredPlanningRequest
    expected_goal: GoalRevisionRef
    expected_head: UUID
    inputs: PlanningReviewInputs
    _original: tuple[object, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.operation) is not PlanningOperation
            or type(self.inputs) is not PlanningReviewInputs
            or not isinstance(self.owner, AuthenticatedWorkerIdentity)
            or not isinstance(self.actor, AuthenticatedWorkerIdentity)
            or type(self.loaded) is not StoredPlanningRequest
            or self.operation.credential is not self.actor
            or self.inputs.factory is not self.services.factory
            or self.inputs.catalog is not self.services.management.catalog
            or self.inputs.store is not self.services.prepared
            or self.owner_scope.principal_id != self.owner.identity.principal_id
            or self.brain
            != recovery_scope(
                _planner(self.services, self.expected_goal), self.action.proposal.action_id
            )
            or (self.brain.principal_id, self.brain.workspace_id)
            != (self.actor.identity.principal_id, self.actor.identity.workspace_id)
        ):
            raise ValueError("Prepared recovery requires its concrete original actor/owner graph")
        object.__setattr__(self, "_original", self._pins())

    @property
    def services(self) -> PlanningServices:
        return self.operation.services

    @property
    def scope(self) -> LedgerScope:
        return recovery_ledger(self.brain)

    def _pins(self) -> tuple[object, ...]:
        return (
            self.operation,
            self.owner,
            self.actor,
            self.inputs,
            self.owner_scope.model_dump_json(),
            self.brain.model_dump_json(),
            self.initial.model_dump_json(),
            self.action.model_dump_json(),
            self.selected,
            self.loaded.prepared.model_dump_json(by_alias=True),
            self.loaded.reference,
            self.loaded.read_end_us,
            self.expected_goal,
            self.expected_head,
        )

    def require_current(self) -> None:
        self.operation.require_admission()
        self.inputs.require_composition()
        current = self._pins()
        if (
            any(a is not b for a, b in zip(current[:4], self._original[:4], strict=True))
            or current[4:] != self._original[4:]
            or self.inputs.store is not self.services.prepared
        ):
            raise ValueError("Original prepared recovery composition changed")
        self.owner.require_time(datetime.now(UTC))
        self.actor.require_time(datetime.now(UTC))
        _settled(self.operation)

    async def validate_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: ActionRecord,
    ) -> CostQuote:
        # Cohesion exception: original proof, actor/static READ and quote must
        # remain visibly ordered in this single native validation transaction.
        self.require_current()
        binding = await _binding(
            self.operation, session, control, self.brain, self.expected_goal, self.expected_head
        )
        if action != self.action or (
            self.loaded.prepared.binding.goal,
            self.loaded.prepared.binding.expected_plan_revision_id,
        ) != (self.expected_goal, self.expected_head):
            raise ValueError("Recovery action or frozen goal/head changed")
        self.operation.end = await self.inputs.validate(
            session,
            control,
            self.owner_scope,
            self.owner.identity,
            action.proposal,
            work,
            binding,
            self.selected,
            self.loaded,
            end_us=self.operation.end,
        )
        required = await self.services.contexts.revalidate_context(
            session,
            control,
            self.loaded.prepared.scope,
            self.actor.identity,
            self.loaded.prepared.context.manifest,
            await db_now(session),
        )
        if (*required, self.loaded.reference.condition) != action.proposal.preconditions:
            raise ValueError("Original actor/source conditions changed")
        await _static(
            self.operation,
            session,
            control,
            self.owner_scope,
            self.owner,
            self.actor,
            binding,
            action,
        )
        selected = await quote_locked(
            self.services, session, control, work, self.loaded.prepared, await db_now(session)
        )
        if selected.quote.amount_usd != action.proposal.estimated_cost_usd:
            raise ValueError("Original pending quote differs from current allowance")
        self.require_current()
        return selected.quote

    def describe(
        self, action: ActionRecord, work: ExecutionSnapshot, quote: CostQuote
    ) -> RecoveredPlanningWait:
        self.require_current()
        value = PreparedPlanningAction(
            action=action, reference=self.loaded.reference, work=work, quote=quote
        )
        value.model_dump_json(by_alias=True)
        self.require_current()
        return RecoveredPlanningWait(value, self.operation.end)


async def recover_prepared_wait(
    services: PlanningServices,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    action_id: UUID,
    expected_hash: str,
    *,
    expected_goal: GoalRevisionRef,
    expected_current_revision_id: UUID,
    end_us: int,
) -> RecoveredPlanningWait:
    """Explicit owner trigger; preserve the exact saved unissued request and original windows."""
    # Cohesion exception: select, out-of-lock private read and final native wait
    # share the one original operation and its actual owned resource graph.
    if (
        not isinstance(owner, AuthenticatedWorkerIdentity)
        or scope.principal_id != owner.identity.principal_id
        or scope.company_id != expected_goal.company_id
        or not isinstance(expected_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
    ):
        raise ValueError("Recovery needs its original signed owner and exact pending action")
    binding = _planner(services, expected_goal)
    if (binding.company_id, binding.workspace_id) != (
        scope.company_id,
        owner.identity.workspace_id,
    ):
        raise ValueError("Recovery owner belongs to another configured company/workspace")
    operation = PlanningOperation(services, "recover-wait:" + str(uuid4()), end_us)
    result: RecoveredPlanningWait | None = None
    try:
        owner.require_time(datetime.now(UTC))
        from nexus.builder.contained_query import clock_us

        before = clock_us()
        operation.shorten(datetime.now(UTC), before, (owner.expires_at,))
        actor = await operation.call(services.identities.current(binding))
        operation.credential = actor
        brain = recovery_scope(binding, action_id)
        inputs = PlanningReviewInputs(
            services.factory,
            services.management.catalog,
            services.prepared.sources,
            services.prepared,
        )

        async def select() -> tuple[ExecutionSnapshot, ActionRecord, PlanningReviewSelection]:
            async with runtime_transaction(
                services.factory, recovery_ledger(brain), actor.identity
            ) as (
                session,
                control,
                _,
            ):
                current = await _binding(
                    operation, session, control, brain, expected_goal, expected_current_revision_id
                )
                work = await execution_row(session, recovery_ledger(brain))
                action = await require_unissued_pending(
                    session, control, work, action_id, expected_hash, await db_now(session)
                )
                await _static(operation, session, control, scope, owner, actor, current, action)
                selected = inputs.select(control, action.proposal, work, current)
                operation.require_admission()
                return snapshot(work), action, selected

        initial, action, selected = await operation.call(select())
        # This concrete actor READ owns its own CC mutex; never nest it in select/final.
        loaded = await operation.call(
            services.prepared.load_actor(brain, actor.identity, action_id, end_us=operation.end)
        )
        operation.end = min(operation.end, loaded.read_end_us)
        check = PreparedWaitRecovery(
            operation,
            scope,
            owner,
            actor,
            brain,
            initial,
            action,
            selected,
            loaded,
            expected_goal,
            expected_current_revision_id,
            inputs,
        )
        check.require_current()
        result = await operation.call(services.execution.recover_prepared_wait(check))
        check.require_current()
    except BaseException as first:
        operation.first = operation.first or first
    operation.finish()
    if operation.first is not None:
        raise operation.first
    assert result is not None
    operation.require_current()
    return result
