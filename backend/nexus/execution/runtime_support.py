"""Shared locked runtime scope, snapshots and lifetime attempt reservations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import cast
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.directory_models import (
    DirectoryCompany,
    DirectoryMembership,
    RegisteredWork,
    WorkPrincipal,
)
from nexus.company.directory_store import _lineage_active
from nexus.execution.runtime_contracts import (
    AttemptKind,
    ExecutionDeniedError,
    ExecutionLease,
    ExecutionRegistration,
    ExecutionSnapshot,
    ExecutionState,
)
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.harness.journal_budget import reconcile_cost
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl
from nexus.harness.limits import LoopCounters

logger = structlog.get_logger()
KINDS = tuple(LoopCounters.model_fields)


async def mark_unknown_intents(
    session: AsyncSession,
    row: ExecutionWork,
    effects: list[EffectIntent],
) -> None:
    """Preserve issued reservations when orphan intent cannot establish outcome or billing."""
    scope = LedgerScope(
        company_id=row.company_id,
        task_id=row.task_id,
        trace_id=row.trace_id,
        principal_id=row.actor_id,
    )
    for effect in effects:
        if effect.state == "intent":
            effect.state = "outcome_unknown"
        await reconcile_cost(session, scope, effect.action_id, None)


def registration_digest(registration: ExecutionRegistration) -> str:
    """Hash the complete normalized application contract, never native client objects."""
    payload = json.dumps(
        registration.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@asynccontextmanager
async def runtime_transaction(
    factory: async_sessionmaker[AsyncSession],
    scope: LedgerScope,
    identity: VerifiedIdentity,
    *,
    allow_inactive: bool = False,
    allow_paused: bool = False,
    owner_read: bool = False,
) -> AsyncIterator[tuple[AsyncSession, CompanyControl, RegisteredWork]]:
    """Lock company control first, then derive current registered scope in one transaction."""
    async with factory() as session, session.begin():
        for key, value in (
            ("nexus.company_id", scope.company_id),
            ("nexus.workspace_id", identity.workspace_id),
            ("nexus.principal_id", identity.principal_id),
        ):
            await session.execute(select(func.set_config(key, str(value), True)))
        try:
            control = await session.scalar(
                select(CompanyControl)
                .where(CompanyControl.company_id == scope.company_id)
                .with_for_update()
            )
            if control is None or (control.paused and not allow_paused):
                raise ExecutionDeniedError("Company is absent or paused")
            work = await require_runtime_scope(
                session,
                control,
                scope,
                identity,
                allow_inactive=allow_inactive,
                owner_read=owner_read,
            )
            yield session, control, work
        except Exception as exc:
            logger.warning(
                "execution_store_rejected",
                task_id=str(scope.task_id),
                trace_id=str(scope.trace_id),
                error_type=type(exc).__name__,
            )
            raise


async def require_runtime_scope(
    session: AsyncSession,
    control: CompanyControl,
    scope: LedgerScope,
    identity: VerifiedIdentity,
    *,
    allow_inactive: bool,
    owner_read: bool,
) -> RegisteredWork:
    """Never turn a lease payload, JWT role or arbitrary work ID into authority."""
    company = await session.get(DirectoryCompany, scope.company_id)
    work = await session.get(RegisteredWork, (scope.company_id, scope.task_id))
    member = await session.get(DirectoryMembership, (scope.company_id, identity.principal_id))
    owner = await session.get(DirectoryMembership, (scope.company_id, control.owner_id))
    if (
        company is None
        or work is None
        or member is None
        or owner is None
        or (
            scope.principal_id != identity.principal_id
            or company.owner_id != control.owner_id
            or company.workspace_id != identity.workspace_id
            or work.workspace_id != identity.workspace_id
            or work.trace_id != scope.trace_id
            or not member.principal_active
            or not member.membership_active
            or not owner.principal_active
            or not owner.membership_active
            or owner.role != "owner"
        )
    ):
        raise ExecutionDeniedError("Current company/workspace/member/work binding is unavailable")
    # Preserve the canonical capability policy's false-owner rejection even on
    # receipt/recovery paths where pause/inactive-work restrictions differ.
    if member.role == "owner" and member.principal_id != control.owner_id:
        raise ExecutionDeniedError("Membership role disagrees with the actual company owner")
    is_owner_read = (
        owner_read and member.principal_id == control.owner_id and member.role == "owner"
    )
    if not is_owner_read and (work.actor_id != scope.principal_id or member.role == "viewer"):
        raise ExecutionDeniedError("Only the registered current actor owns execution")
    grant = await session.get(WorkPrincipal, (scope.company_id, scope.task_id, work.actor_id))
    if grant is None or (
        not allow_inactive
        and (
            not company.company_active
            or not company.workspace_active
            or not await _lineage_active(session, work)
        )
    ):
        raise ExecutionDeniedError("Current work grant or active ancestry is unavailable")
    return work


async def db_now(session: AsyncSession) -> datetime:
    """Use the database clock after acquiring locks; clients cannot extend a lease by lying."""
    value: datetime | None = await session.scalar(select(func.clock_timestamp()))
    if value is None or value.utcoffset() is None:
        raise ExecutionDeniedError("Database clock is unavailable")
    return value


async def execution_row(session: AsyncSession, scope: LedgerScope) -> ExecutionWork:
    """Lock one existing immutable logical run after the company lock."""
    row = await session.scalar(
        select(ExecutionWork)
        .where(
            ExecutionWork.company_id == scope.company_id,
            ExecutionWork.task_id == scope.task_id,
        )
        .with_for_update()
    )
    if row is None:
        raise ExecutionDeniedError("Logical execution has not been registered")
    return row


def snapshot(row: ExecutionWork) -> ExecutionSnapshot:
    """Revalidate immutable stored JSON and expose explicit persisted counters."""
    registration = ExecutionRegistration.model_validate_json(row.registration_json)
    if registration_digest(registration) != row.registration_hash or (
        registration.work.company_id,
        registration.work.task_id,
        registration.work.trace_id,
        registration.run_id,
        registration.workflow_name,
        registration.workflow_version,
        registration.model_profile,
        registration.model_registry_version,
    ) != (
        row.company_id,
        row.task_id,
        row.trace_id,
        row.run_id,
        row.workflow_name,
        row.workflow_version,
        row.model_profile,
        row.model_registry_version,
    ):
        raise ExecutionDeniedError("Stored logical execution binding is invalid")
    return ExecutionSnapshot(
        company_id=row.company_id,
        registration=registration,
        workspace_id=row.workspace_id,
        actor_id=row.actor_id,
        parent_task_id=row.parent_task_id,
        state=cast(ExecutionState, row.state),
        counters=LoopCounters.model_validate(
            {kind: getattr(row, f"{kind}_used") for kind in KINDS}
        ),
        delegated=LoopCounters.model_validate(
            {kind: getattr(row, f"{kind}_delegated") for kind in KINDS}
        ),
        fence=row.fence,
        worker_id=row.worker_id,
        lease_principal_id=row.lease_principal_id,
        expires_at=row.lease_until,
        segment_number=row.segment_number,
        segment_id=row.segment_id,
        waiting_action_id=row.waiting_action_id,
    )


def lease_scope(lease: ExecutionLease) -> LedgerScope:
    """Derive the ledger identity, still requiring fresh verified membership in the store."""
    return LedgerScope(
        company_id=lease.company_id,
        task_id=lease.task_id,
        trace_id=lease.trace_id,
        principal_id=lease.actor_id,
    )


def require_lease(
    row: ExecutionWork, lease: ExecutionLease, now: datetime, *, execute: bool = False
) -> None:
    """A stale worker cannot mutate, reconcile or authorize by presenting an old token."""
    snapshot(row)
    if (
        (
            row.company_id,
            row.task_id,
            row.trace_id,
            row.actor_id,
            row.workspace_id,
            row.run_id,
            row.workflow_version,
            row.segment_id,
            row.worker_id,
            row.fence,
            row.lease_mode,
        )
        != (
            lease.company_id,
            lease.task_id,
            lease.trace_id,
            lease.actor_id,
            lease.workspace_id,
            lease.run_id,
            lease.workflow_version,
            lease.segment_id,
            lease.worker_id,
            lease.fence,
            lease.mode,
        )
        or row.lease_until is None
        or row.lease_until <= now
    ):
        raise ExecutionDeniedError("Execution lease is stale, expired or differently bound")
    if row.lease_principal_id != lease.actor_id:
        raise ExecutionDeniedError("This fence belongs to another recording principal")
    if execute and (lease.mode != "execute" or row.state not in {"running", "verifying"}):
        raise ExecutionDeniedError("Lease/state cannot authorize new attempts or effects")


async def reserve_locked_attempt(
    session: AsyncSession, row: ExecutionWork, kind: AttemptKind, attempt_id: UUID, now: datetime
) -> None:
    """Consume a lifetime slot before an attempt; no success-only refund exists."""
    if kind not in KINDS:
        raise ExecutionDeniedError("Unknown attempt kind")
    previous = await session.get(ExecutionAttempt, (row.company_id, row.task_id, attempt_id))
    if previous is not None:
        if previous.kind != kind:
            raise ExecutionDeniedError("Attempt identity already binds another kind")
        return
    used, delegated, limit = (
        getattr(row, f"{kind}_{suffix}") for suffix in ("used", "delegated", "limit")
    )
    if used + delegated >= limit:
        raise ExecutionDeniedError(f"Logical lifetime quota exhausted: {kind}")
    setattr(row, f"{kind}_used", used + 1)
    session.add(
        ExecutionAttempt(
            company_id=row.company_id,
            task_id=row.task_id,
            attempt_id=attempt_id,
            trace_id=row.trace_id,
            kind=kind,
            fence=row.fence,
            reserved_at=now,
        )
    )
    await session.flush()
