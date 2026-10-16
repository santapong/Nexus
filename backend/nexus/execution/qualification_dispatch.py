"""Owner-only metadata staging and atomic fixed-workflow dispatch; no provider invocation."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.contained_query import clock_us
from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.directory_models import RegisteredWork
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.scheduling_contracts import WorkflowRegistration
from nexus.company.management.scheduling_queue import _enqueue_exact
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.core.llm.qualification_contracts import APPLICATION, QUEUE, VERSION, WORKFLOW
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_store import reserve_dispatch
from nexus.execution.effect_support import require_effect_authority
from nexus.execution.qualification_read_contracts import QualificationDispatchRecord
from nexus.execution.qualification_reads import (
    QualificationReader,
    qualification_rows,
    require_current_recipe_locked,
)
from nexus.execution.qualification_service import QualificationPreparationService
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_store import ExecutionStore, next_segment_id
from nexus.execution.runtime_support import db_now, snapshot
from nexus.harness.approvals import ApprovalContext, require_exact_approval
from nexus.harness.journal_authorization import authorize_registered_pending_locked
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_contracts import ActionRecord, LedgerScope
from nexus.harness.journal_models import CompanyControl, CostHold, DailyBudget, WorkBudget
from nexus.harness.journal_reservations import require_current_work_caps
from nexus.harness.lifecycle import ActionState

REGISTRATION = WorkflowRegistration(
    workflow_name=WORKFLOW, workflow_version=VERSION, queue_name=QUEUE, application_name=APPLICATION
)


def _current(end_us: int) -> None:
    if type(end_us) is not int or not 0 < clock_us() < end_us:
        raise TimeoutError("Qualification original dispatch deadline expired")


def _ledger(work: ExecutionWork) -> LedgerScope:
    return LedgerScope(
        company_id=work.company_id,
        principal_id=work.actor_id,
        task_id=work.task_id,
        trace_id=work.trace_id,
    )


@dataclass(frozen=True, slots=True)
class QualificationDispatchService:
    preparation: QualificationPreparationService
    execution: ExecutionStore
    _owners: list[asyncio.Task[object]] = field(default_factory=list, init=False, repr=False)
    _secondary: list[str] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self._composition()

    def _composition(self) -> None:
        if (
            type(self.execution) is not ExecutionStore
            or self.execution._factory is not self.preparation.factory
        ):
            raise ValueError("Qualification dispatch must share its actual native factory")

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        return tuple(task for task in self._owners if not task.done() or task.cancelled())

    def _track[T](self, task: asyncio.Task[T]) -> asyncio.Task[T]:
        self._owners[:] = list(self.pending_owners())
        self._owners.append(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda value: None if value.cancelled() else value.exception())
        return task

    async def _await[T](self, task: asyncio.Task[T], end_us: int) -> T:
        async with asyncio.timeout(max(0, end_us - clock_us()) / 1_000_000):
            value = await asyncio.shield(task)
        _current(end_us)
        self._composition()
        return value

    async def _retire(
        self,
        task: asyncio.Task[object],
        identity: VerifiedIdentity,
        lease: ExecutionLease | None,
    ) -> None:
        """Wait actual original leaf first. Never continue staging/dispatch after caller failed."""
        try:
            result = await asyncio.shield(task)
            if lease is not None:
                return  # Successful await_approval already revoked that exact lease.
            if not isinstance(result, ExecutionLease):
                raise ValueError("Staging claim returned no actual lease")
            lease = result
        except BaseException as error:
            if lease is None:
                self._secondary[:] = [*self._secondary, type(error).__name__][-16:]
                return
        try:
            # Resource-only retirement remains bound to the original immutable factory.
            await ExecutionStore(self.preparation.factory).release(lease, identity)
        except BaseException as error:
            self._secondary[:] = [*self._secondary, type(error).__name__][-16:]

    def _failed(
        self,
        first: BaseException,
        task: asyncio.Task[object],
        identity: VerifiedIdentity,
        lease: ExecutionLease | None,
    ) -> None:
        self._track(asyncio.create_task(self._retire(task, identity, lease)))
        first.__dict__["_nexus_qualification_pending"] = self.pending_owners()

    async def _stage(
        self,
        scope: LedgerScope,
        identity: VerifiedIdentity,
        action_id: UUID,
        end_us: int,
    ) -> None:
        _current(end_us)
        self._composition()
        claimed = self._track(
            asyncio.create_task(self.execution.claim(scope, identity, uuid4(), ttl_seconds=15))
        )
        try:
            lease = await self._await(claimed, end_us)
        except BaseException as first:
            self._failed(first, cast(asyncio.Task[object], claimed), identity, None)
            raise
        try:
            _current(end_us)
            self._composition()
        except BaseException as first:
            self._failed(first, cast(asyncio.Task[object], claimed), identity, None)
            raise
        waiting = self._track(
            asyncio.create_task(self.execution.await_approval(lease, identity, action_id))
        )
        try:
            saved = await self._await(waiting, end_us)
            if (
                saved.state != "awaiting_approval"
                or saved.waiting_action_id != action_id
                or saved.worker_id is not None
            ):
                raise ValueError("Staging did not close its exact pending-action lease")
        except BaseException as first:
            self._failed(first, cast(asyncio.Task[object], waiting), identity, lease)
            raise

    async def _fresh(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
        expected_hash: str,
    ) -> tuple[ExecutionWork, ActionRecord, bool]:
        row, work, record, recipe, existing = await qualification_rows(
            self.preparation, session, scope, action_id
        )
        if existing is not None:
            raise ManagementDeniedError("Existing dispatch must use its immutable binding")
        quote = await require_current_recipe_locked(
            self.preparation, session, control, scope, identity, recipe
        )
        now = await db_now(session)
        if (
            work.actor_id != identity.principal_id
            or work.workspace_id != identity.workspace_id
            or record.proposal_hash != expected_hash
            or row.consumed_at is not None
            or record.state != ActionState.AWAITING_APPROVAL
            or record.approval is None
            or record.proposal.estimated_cost_usd != quote.amount_usd
            or work.worker_id is not None
            or work.lease_until is not None
            or work.state not in {"eligible", "verifying", "running", "awaiting_approval"}
            or (work.waiting_action_id is not None and work.waiting_action_id != action_id)
            or (work.state == "awaiting_approval" and work.waiting_action_id != action_id)
            or work.model_requests_used + work.model_requests_delegated >= work.model_requests_limit
        ):
            raise ManagementDeniedError("Qualification pending staging is unavailable or changed")
        require_exact_approval(
            record.proposal,
            record.approval,
            ApprovalContext(
                company_id=scope.company_id,
                owner_id=control.owner_id,
                actor_id=identity.principal_id,
                now=now,
                policy_version=control.policy_version,
                price_version=control.price_version,
                paused=control.paused,
                resources=(),
            ),
        )
        if (
            await session.scalar(
                select(EffectIntent.action_id).where(
                    EffectIntent.company_id == work.company_id,
                    EffectIntent.task_id == work.task_id,
                    EffectIntent.state.in_(("intent", "outcome_unknown")),
                )
            )
            is not None
        ):
            raise ManagementDeniedError("Qualification unresolved intent prevents new dispatch")
        if await session.get(CostHold, action_id) is not None:
            raise ManagementDeniedError("Unconsumed qualification action already has a hold")
        registered = await session.get(RegisteredWork, (work.company_id, work.task_id))
        budget = await session.get(WorkBudget, (work.company_id, work.task_id))
        day = await session.get(DailyBudget, (work.company_id, billing_day(now)))
        if (
            registered is None
            or not registered.active
            or (budget.held_usd + budget.spent_usd if budget else 0) + quote.amount_usd
            > min(control.work_cap_usd, registered.allocation_usd - registered.delegated_usd)
            or (day.held_usd + day.spent_usd if day else 0) + quote.amount_usd
            > control.daily_cap_usd
        ):
            raise ManagementDeniedError("Qualification current lifetime/day funds are exhausted")
        return work, record, work.state == "awaiting_approval"

    async def dispatch(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
        expected_hash: str,
        *,
        end_us: int,
    ) -> QualificationDispatchRecord:
        _current(end_us)
        self._composition()
        end_us = min(end_us, clock_us() + 30_000_000)
        if type(expected_hash) is not str or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
            raise ValueError("Qualification expected action hash is invalid")
        async with asyncio.timeout(max(0, end_us - clock_us()) / 1_000_000):
            async with management_owner_transaction(
                self.preparation.factory, scope, identity, allow_paused=True
            ) as (session, control, _):
                _, _, record, _, existing = await qualification_rows(
                    self.preparation, session, scope, action_id
                )
                if record.proposal_hash != expected_hash:
                    raise ManagementDeniedError("Qualification expected action hash changed")
                if existing is not None:
                    _current(end_us)
                    return QualificationDispatchRecord(
                        command=existing, workflow_id=existing.workflow_id, disposition="existing"
                    )
                work, _, waiting = await self._fresh(
                    session, control, scope, identity, action_id, expected_hash
                )
                ledger = _ledger(work)
        _current(end_us)
        self._composition()
        if not waiting:
            await self._stage(ledger, identity, action_id, end_us)
        async with asyncio.timeout(max(0, end_us - clock_us()) / 1_000_000):
            async with management_owner_transaction(
                self.preparation.factory, scope, identity, allow_paused=True
            ) as (session, control, _):
                _, _, _, _, existing = await qualification_rows(
                    self.preparation, session, scope, action_id
                )
                if existing is not None:
                    _current(end_us)
                    return QualificationDispatchRecord(
                        command=existing, workflow_id=existing.workflow_id, disposition="existing"
                    )
                work, _, _ = await self._fresh(
                    session, control, scope, identity, action_id, expected_hash
                )
                approved = await authorize_registered_pending_locked(
                    session, control, _ledger(work), identity, action_id, await db_now(session), ()
                )
                command = SegmentCommand(
                    company_id=work.company_id,
                    task_id=work.task_id,
                    trace_id=work.trace_id,
                    actor_id=work.actor_id,
                    workspace_id=work.workspace_id,
                    run_id=work.run_id,
                    action_id=action_id,
                    segment_id=next_segment_id(snapshot(work)),
                )
                await reserve_dispatch(
                    session, command, workflow_name=WORKFLOW, workflow_version=VERSION
                )
                await _enqueue_exact(session, command, REGISTRATION)
                _, _, _, recipe, _ = await qualification_rows(
                    self.preparation, session, scope, action_id
                )
                quote = await require_current_recipe_locked(
                    self.preparation, session, control, scope, identity, recipe
                )
                now = await db_now(session)
                await require_effect_authority(
                    session, control, work, action_id, now, (), _ledger(work), identity
                )
                await require_current_work_caps(session, control, _ledger(work))
                hold = await session.get(CostHold, action_id)
                day = await session.get(DailyBudget, (work.company_id, billing_day(now)))
                if (
                    hold is None
                    or hold.state != "held"
                    or hold.actual_usd is not None
                    or hold.amount_usd != quote.amount_usd
                    or approved.proposal.estimated_cost_usd != quote.amount_usd
                    or (day.held_usd + day.spent_usd if day else 0)
                    + (hold.amount_usd if hold.day != billing_day(now) else 0)
                    > control.daily_cap_usd
                ):
                    raise ManagementDeniedError("Qualification final reservation differs")
                _current(end_us)
                self._composition()
                return QualificationDispatchRecord(
                    command=command, workflow_id=command.workflow_id, disposition="enqueued"
                )


@dataclass(frozen=True, slots=True)
class QualificationApiServices:
    preparation: QualificationPreparationService
    dispatch: QualificationDispatchService
    reads: QualificationReader
    directory: PersistentCompanyDirectory = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.dispatch.preparation is not self.preparation
            or self.reads.preparation is not self.preparation
        ):
            raise ValueError("Qualification API must retain one original server catalog/factory")
        object.__setattr__(self, "directory", PersistentCompanyDirectory(self.preparation.factory))
