"""Explicit exact C unissued-wait recovery through the existing finite native CAS."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope
from nexus.company.brain.base import BrainReadScope
from nexus.company.management.coding_prepared_contracts import StoredCodingRequest
from nexus.company.management.goals import GoalRevisionRef
from nexus.company.management.owner_view_sources import owner_brain_scope
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.core.llm.company_pricing import CostQuote
from nexus.execution.coding_context import quote_locked
from nexus.execution.coding_lifecycle_bindings import approved_r2_locked, static_read_locked
from nexus.execution.coding_operation import CodingOperation
from nexus.execution.coding_owner_reads import CodingOwnerReader
from nexus.execution.coding_preparation import PreparedCodingAction
from nexus.execution.coding_services import CodingServices
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
class RecoveredCodingWait:
    value: PreparedCodingAction
    read_end_us: int


@dataclass(frozen=True, slots=True)
class PreparedCodingWaitRecovery:
    """Only this exact real graph enters C CAS; descriptions/foreign callbacks cannot."""

    operation: CodingOperation
    owner_scope: CompanyControlScope
    owner: AuthenticatedWorkerIdentity
    actor: AuthenticatedWorkerIdentity
    brain: BrainReadScope
    initial: ExecutionSnapshot
    action: ActionRecord
    loaded: StoredCodingRequest
    owner_loaded: StoredCodingRequest
    expected_goal: GoalRevisionRef
    expected_head: UUID
    inputs: CodingOwnerReader
    _original: tuple[object, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.operation) is not CodingOperation
            or type(self.inputs) is not CodingOwnerReader
            or self.inputs.services is not self.services
            or self.operation.credential is not self.actor
            or self.loaded.prepared != self.owner_loaded.prepared
            or self.loaded.reference != self.owner_loaded.reference
            or self.owner_scope.principal_id != self.owner.identity.principal_id
        ):
            raise ValueError("Coding recovery original owner/actor/input graph differs")
        object.__setattr__(self, "_original", self._pins())
        self.require_current()

    @property
    def services(self) -> CodingServices:
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
            self.loaded,
            self.owner_loaded,
            self.owner_scope.model_dump_json(),
            self.brain.model_dump_json(),
            self.initial.model_dump_json(),
            self.action.model_dump_json(),
            self.loaded.prepared.model_dump_json(by_alias=True),
            self.loaded.reference,
            self.loaded.read_end_us,
            self.owner_loaded.read_end_us,
            self.expected_goal,
            self.expected_head,
        )

    def require_current(self) -> None:
        self.operation.require_admission()
        self.inputs.require_composition()
        actual = self._pins()
        if (
            any(a is not z for a, z in zip(actual[:6], self._original[:6], strict=True))
            or actual[6:] != self._original[6:]
        ):
            raise ValueError("Coding original recovery composition changed")
        store = self.operation.prepared
        store.require_loaded(self.loaded, self.actor, None, mode="actor", end_us=self.operation.end)
        store.require_loaded(
            self.owner_loaded, self.owner, None, mode="owner", end_us=self.operation.end
        )
        if any(
            value is not self.operation and (value.running or value.pending_owners())
            for value in self.services._operations.values()
        ):
            raise ValueError("Coding recovery retains another original operation")
        self.owner.require_time(datetime.now(UTC))
        self.actor.require_time(datetime.now(UTC))

    async def validate_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: ActionRecord,
    ) -> CostQuote:
        """Cohesion exception: both original witnesses/loads, static source and quote share CAS."""
        self.require_current()
        bundle, end = await approved_r2_locked(
            self.services, session, control, self.owner_scope, self.owner, self.operation.end
        )
        if (
            bundle.plan.plan_revision_id != self.expected_head
            or bundle.plan.payload.goal != self.expected_goal
            or action != self.action
            or self.loaded.prepared.binding.plan != bundle.binding.plan
        ):
            raise ValueError("Coding recovery actual r2/head/action changed")
        store = self.operation.prepared
        end = min(
            end,
            await store.validate_loaded_locked(
                session,
                control,
                owner_brain_scope(self.owner_scope, self.owner.identity),
                self.owner_loaded,
                self.owner,
                None,
                mode="owner",
                now=await db_now(session),
            ),
        )
        end = min(
            end,
            await store.validate_loaded_locked(
                session,
                control,
                self.brain,
                self.loaded,
                self.actor,
                None,
                mode="actor",
                now=await db_now(session),
            ),
        )
        end = await static_read_locked(
            self.services,
            session,
            control,
            self.owner_scope,
            self.owner,
            bundle.binding,
            action,
            end,
        )
        actor_scope = CompanyControlScope(
            company_id=self.scope.company_id,
            principal_id=self.actor.identity.principal_id,
            operation_id=self.owner_scope.operation_id,
            trace_id=self.owner_scope.trace_id,
        )
        end = await static_read_locked(
            self.services, session, control, actor_scope, self.actor, bundle.binding, action, end
        )
        self.operation.end = min(self.operation.end, end)
        quoted = await quote_locked(
            self.services, session, control, work, self.loaded.prepared, await db_now(session)
        )
        if quoted.quote.amount_usd != action.proposal.estimated_cost_usd:
            raise ValueError("Coding recovery original quotation differs")
        self.require_current()
        return quoted.quote

    def describe(
        self, action: ActionRecord, work: ExecutionSnapshot, quote: CostQuote
    ) -> RecoveredCodingWait:
        self.require_current()
        value = PreparedCodingAction(
            action=action, reference=self.loaded.reference, work=work, quote=quote
        )
        value.model_dump_json(by_alias=True)
        self.require_current()
        return RecoveredCodingWait(value, self.operation.end)


async def recover_prepared_wait(
    services: CodingServices,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    action_id: UUID,
    expected_hash: str,
    *,
    expected_goal: GoalRevisionRef,
    expected_current_revision_id: UUID,
    end_us: int,
    inputs: CodingOwnerReader | None = None,
) -> RecoveredCodingWait:
    """Original owner and C recheck the same zero-issued wait without new allowance.

    Cohesion exception: capture both genuine witnesses and actual store seals,
    then retain the exact existing CAS task under the original operation end.
    """
    admission = services.management.catalog.nexus_coding_admission
    assert admission is not None
    if (
        type(owner) is not AuthenticatedWorkerIdentity
        or (
            scope.company_id,
            scope.principal_id,
            owner.identity.principal_id,
            owner.identity.workspace_id,
        )
        != (
            admission.company_id,
            admission.procedure.binding.actor_id,
            admission.procedure.binding.actor_id,
            admission.procedure.binding.workspace_id,
        )
        or expected_goal != admission.goal
        or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
    ):
        raise ValueError(
            "Coding recovery requires its original actual owner and exact configured Goal/hash"
        )
    inputs = inputs if inputs is not None else CodingOwnerReader(services)
    operation = CodingOperation(services, "recover-wait:" + str(uuid4()), end_us)
    result = None
    try:
        first = await operation.call(inputs.read(scope, owner, action_id, end_us=operation.end))
        operation.end = min(operation.end, first.read_end_us)
        actor = await operation.call(services.identities.current(admission.slots[1].child.binding))
        operation.credential = actor
        brain = recovery_scope(admission.slots[1].child.binding, action_id)
        services.require_actor_scope(recovery_ledger(brain), actor)

        async def select() -> tuple[ExecutionSnapshot, ActionRecord]:
            async with runtime_transaction(
                services.factory, recovery_ledger(brain), actor.identity
            ) as (session, control, _):
                bundle, end = await approved_r2_locked(
                    services, session, control, scope, owner, operation.end
                )
                operation.end = min(operation.end, end)
                if bundle.plan.plan_revision_id != expected_current_revision_id:
                    raise ValueError("Coding recovery actual r2 differs")
                work = await execution_row(session, recovery_ledger(brain))
                action = await require_unissued_pending(
                    session, control, work, action_id, expected_hash, await db_now(session)
                )
                operation.require_admission()
                return snapshot(work), action

        initial, action = await operation.call(select())
        store = operation.prepared
        owner_loaded = await operation.call(
            store.load_owner(scope, owner, action_id, end_us=operation.end)
        )
        operation.end = min(operation.end, owner_loaded.read_end_us)
        loaded = await operation.call(
            store.load_actor(brain, actor, action_id, end_us=operation.end)
        )
        operation.end = min(operation.end, loaded.read_end_us)
        check = PreparedCodingWaitRecovery(
            operation,
            scope,
            owner,
            actor,
            brain,
            initial,
            action,
            loaded,
            owner_loaded,
            expected_goal,
            expected_current_revision_id,
            inputs,
        )
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
