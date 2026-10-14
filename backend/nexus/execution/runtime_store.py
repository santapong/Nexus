"""Persisted logical work, lifetime counters and database-clock fenced worker leases."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid5

from pydantic import StrictBool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.cancellation_support import require_not_cancelled
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.execution.management_checks import (
    ManagementArtifactFreshness,
    require_management_execution,
)
from nexus.execution.runtime_contracts import (
    AttemptKind,
    ExecutionDeniedError,
    ExecutionLease,
    ExecutionRegistration,
    ExecutionSnapshot,
)
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_registration import register_locked
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    mark_unknown_intents,
    require_lease,
    reserve_locked_attempt,
    runtime_transaction,
    snapshot,
)
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CostHold, JournalAction


def next_segment_id(value: ExecutionSnapshot) -> UUID:
    """Derive the next segment ID without allocating new work or new quota."""
    return uuid5(
        value.registration.run_id, f"nexus-execution-segment-v1:{value.segment_number + 1}"
    )


def _lease(row: ExecutionWork) -> ExecutionLease:
    return ExecutionLease.model_validate(
        {
            "company_id": row.company_id,
            "task_id": row.task_id,
            "trace_id": row.trace_id,
            "actor_id": row.actor_id,
            "workspace_id": row.workspace_id,
            "run_id": row.run_id,
            "workflow_version": row.workflow_version,
            "segment_id": row.segment_id,
            "worker_id": row.worker_id,
            "fence": row.fence,
            "expires_at": row.lease_until,
            "mode": row.lease_mode,
        }
    )


def _ttl(value: int) -> timedelta:
    if type(value) is not int or not 1 <= value <= 300:
        raise ExecutionDeniedError("Lease TTL must be an integer from 1 to 300 seconds")
    return timedelta(seconds=value)


async def _unresolved(session: AsyncSession, row: ExecutionWork) -> list[EffectIntent]:
    return list(
        (
            await session.scalars(
                select(EffectIntent).where(
                    EffectIntent.company_id == row.company_id,
                    EffectIntent.task_id == row.task_id,
                    EffectIntent.state.in_(("intent", "outcome_unknown")),
                )
            )
        ).all()
    )


async def _waiting_authorized(session: AsyncSession, row: ExecutionWork) -> None:
    action = await session.get(JournalAction, row.waiting_action_id)
    hold = await session.get(CostHold, row.waiting_action_id)
    if (
        action is None
        or hold is None
        or (action.company_id, action.task_id, action.trace_id)
        != (
            row.company_id,
            row.task_id,
            row.trace_id,
        )
        or action.state != "authorized"
        or action.consumed_at is None
        or hold.state != "held"
    ):
        raise ExecutionDeniedError("Waiting segment lacks committed exact authorization/cost hold")


class ExecutionStore:
    """Transactions own CompanyControl first; DBOS queue/workflow integration is external."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        *,
        management_catalog: PlanAdmissionCatalog | None = None,
        management_artifacts: BoundedArtifactReader | None = None,
        management_freshness: ManagementArtifactFreshness | None = None,
    ) -> None:
        self._factory = factory
        self._management_catalog = management_catalog
        self._management_artifacts = management_artifacts
        self._management_freshness = management_freshness

    async def recover_dispatched(
        self,
        scope: LedgerScope,
        identity: VerifiedIdentity,
        worker_id: UUID,
        segment_id: UUID,
        *,
        ttl_seconds: int = 60,
    ) -> ExecutionLease:
        """Recover a permanent same-segment dispatch under a new fence, never new quota."""
        from nexus.execution.runtime_recovery import recover_locked

        duration = _ttl(ttl_seconds)
        async with runtime_transaction(
            self._factory, scope, identity, allow_paused=True, allow_inactive=True
        ) as (session, control, _):
            row = await execution_row(session, scope)
            return _lease(
                await recover_locked(
                    session,
                    control,
                    row,
                    scope,
                    identity,
                    worker_id,
                    segment_id,
                    duration,
                    management_catalog=self._management_catalog,
                    management_artifacts=self._management_artifacts,
                    management_freshness=self._management_freshness,
                )
            )

    async def release(
        self, lease: ExecutionLease, identity: VerifiedIdentity, *, blocked: StrictBool = False
    ) -> ExecutionSnapshot:
        """Revoke current worker capacity without resetting counters or completing work."""
        from nexus.execution.runtime_recovery import release_locked

        if type(blocked) is not bool:
            raise ExecutionDeniedError("Blocked release requires a literal boolean")
        async with runtime_transaction(
            self._factory, lease_scope(lease), identity, allow_paused=True, allow_inactive=True
        ) as (session, _, _):
            row = await execution_row(session, lease_scope(lease))
            require_lease(row, lease, await db_now(session))
            await release_locked(session, row, blocked=blocked)
            return snapshot(row)

    async def register(
        self, request: ExecutionRegistration, scope: LedgerScope, identity: VerifiedIdentity
    ) -> ExecutionSnapshot:
        """Initialize one registered logical run or return its exact immutable replay."""
        request = ExecutionRegistration.model_validate_json(request.model_dump_json())
        async with runtime_transaction(self._factory, scope, identity) as (session, _, registered):
            return snapshot(await register_locked(session, request, registered))

    async def get(self, scope: LedgerScope, identity: VerifiedIdentity) -> ExecutionSnapshot:
        """Read trusted persisted state without resetting counters or acquiring a worker."""
        async with runtime_transaction(
            self._factory, scope, identity, allow_paused=True, allow_inactive=True, owner_read=True
        ) as (session, _, _):
            return snapshot(await execution_row(session, scope))

    async def claim(
        self,
        scope: LedgerScope,
        identity: VerifiedIdentity,
        worker_id: UUID,
        *,
        ttl_seconds: int = 60,
        reconcile_only: bool = False,
        segment_id: UUID | None = None,
    ) -> ExecutionLease:
        """Acquire a new segment/fence; orphan intent becomes unknown before any new owner."""
        duration = _ttl(ttl_seconds)
        async with runtime_transaction(
            self._factory,
            scope,
            identity,
            allow_paused=reconcile_only,
            allow_inactive=reconcile_only,
        ) as (session, control, _):
            row = await execution_row(session, scope)
            now = await db_now(session)
            if not reconcile_only:
                await require_management_execution(
                    session,
                    control,
                    row,
                    identity,
                    self._management_catalog,
                    self._management_artifacts,
                    self._management_freshness,
                )
                now = await db_now(session)
            if row.state == "blocked" and not reconcile_only:
                raise ExecutionDeniedError(
                    "Blocked work requires a later explicit controlled resume"
                )
            if row.worker_id is not None and row.lease_until is not None and row.lease_until > now:
                if (
                    row.worker_id == worker_id
                    and row.lease_principal_id == scope.principal_id
                    and segment_id is not None
                    and row.segment_id == segment_id
                    and row.lease_mode == ("reconcile" if reconcile_only else "execute")
                ):
                    return _lease(row)
                raise ExecutionDeniedError("Logical work already has a live lease")
            unresolved = await _unresolved(session, row)
            await mark_unknown_intents(session, row, unresolved)
            if reconcile_only and not unresolved:
                raise ExecutionDeniedError(
                    "Reconciliation lease requires an already-issued unresolved effect"
                )
            if not reconcile_only and row.state == "awaiting_approval":
                await _waiting_authorized(session, row)
            expected_segment = next_segment_id(snapshot(row))
            if segment_id is not None and segment_id != expected_segment:
                raise ExecutionDeniedError(
                    "Continuation segment ID differs from persistent run/sequence"
                )
            row.fence += 1
            row.segment_number += 1
            row.segment_id, row.worker_id = expected_segment, worker_id
            row.lease_principal_id = row.actor_id
            row.lease_until, row.lease_mode = (
                now + duration,
                "reconcile" if reconcile_only else "execute",
            )
            row.state = (
                "outcome_unknown"
                if unresolved
                else ("verifying" if row.state == "verifying" else "running")
            )
            row.waiting_action_id = None
            await session.flush()
            return _lease(row)

    async def renew(
        self, lease: ExecutionLease, identity: VerifiedIdentity, *, ttl_seconds: int = 60
    ) -> ExecutionLease:
        """Extend only the currently owned, unexpired DB lease without changing its fence."""
        duration = _ttl(ttl_seconds)
        async with runtime_transaction(
            self._factory,
            lease_scope(lease),
            identity,
            allow_paused=lease.mode == "reconcile",
            allow_inactive=lease.mode == "reconcile",
        ) as (session, _, _):
            row = await execution_row(session, lease_scope(lease))
            now = await db_now(session)
            require_lease(row, lease, now)
            if lease.mode == "execute":
                await require_not_cancelled(session, row.company_id, row.task_id)
            row.lease_until = (
                max(row.lease_until, now + duration) if row.lease_until else now + duration
            )
            await session.flush()
            return _lease(row)

    async def reserve_attempt(
        self, lease: ExecutionLease, identity: VerifiedIdentity, kind: AttemptKind, attempt_id: UUID
    ) -> ExecutionSnapshot:
        """Consume an idempotently named lifetime attempt; failure does not refund it."""
        async with runtime_transaction(self._factory, lease_scope(lease), identity) as (
            session,
            _,
            _,
        ):
            row = await execution_row(session, lease_scope(lease))
            now = await db_now(session)
            require_lease(row, lease, now, execute=True)
            await require_not_cancelled(session, row.company_id, row.task_id)
            await reserve_locked_attempt(session, row, kind, attempt_id, now)
            return snapshot(row)

    async def await_approval(
        self, lease: ExecutionLease, identity: VerifiedIdentity, action_id: UUID
    ) -> ExecutionSnapshot:
        """Persist pending owner wait, revoke current lease and release execution capacity."""
        async with runtime_transaction(
            self._factory, lease_scope(lease), identity, allow_paused=True
        ) as (session, _, _):
            row = await execution_row(session, lease_scope(lease))
            require_lease(row, lease, await db_now(session), execute=True)
            action = await session.get(JournalAction, action_id)
            if action is None or (
                action.company_id,
                action.task_id,
                action.trace_id,
                action.state,
            ) != (
                row.company_id,
                row.task_id,
                row.trace_id,
                "awaiting_approval",
            ):
                raise ExecutionDeniedError(
                    "Approval wait must bind this work's committed pending action"
                )
            proposal = ActionProposal.model_validate_json(action.proposal_json)
            if proposal.actor_id != row.actor_id or await _unresolved(session, row):
                raise ExecutionDeniedError(
                    "An unresolved effect cannot become a fresh approval wait"
                )
            row.state, row.waiting_action_id = "awaiting_approval", action_id
            row.fence += 1
            row.worker_id = row.lease_until = row.lease_mode = row.lease_principal_id = None
            await session.flush()
            return snapshot(row)
