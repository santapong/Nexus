"""Bounded exact notification lease acquisition; never retry an effect or renew a credential."""

from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.management.cancellation_support import require_not_cancelled
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.managed_contracts import NativeNotificationSelection
from nexus.company.notifications.worker_authorization import current_prepared_admission
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.effect_support import require_effect_authority
from nexus.execution.management_checks import require_management_execution
from nexus.execution.notification_dispatch_read import (
    require_issued_binding,
    require_notification_command,
)
from nexus.execution.notification_worker_services import NotificationDispatchWorkerServices
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_recovery import dispatched_binding
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    require_runtime_scope,
    runtime_transaction,
)
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.journal_submission import pending_action_record

MAX_ACQUISITION_SECONDS = 310
_DENIED = "Notification durable lease acquisition is unavailable"


async def require_wait_admission(
    session: AsyncSession,
    control: CompanyControl,
    services: NotificationDispatchWorkerServices,
    scope: LedgerScope,
    credential: AuthenticatedWorkerIdentity,
    guard: NotificationOperationGuard,
    command: SegmentCommand,
    work: ExecutionWork,
) -> datetime:
    """Only exact issued metadata permits historical waiting; fresh work retains full permission."""
    # Cohesive admission boundary: all current source/approval/recipient captures
    # remain together through the one final clock returned to the waiting preflight.
    row = await session.get(JournalAction, command.action_id)
    if row is None:
        raise ExecutionDeniedError(_DENIED)
    record = pending_action_record(row)
    if record.proposal_hash != action_hash(record.proposal):
        raise ExecutionDeniedError(_DENIED)
    parameters = require_notification_command(
        guard.registration.sender, record.proposal, command, services.dispatcher.resource_symbol
    )
    unresolved = tuple(
        (
            await session.scalars(
                select(EffectIntent.action_id)
                .where(
                    EffectIntent.company_id == command.company_id,
                    EffectIntent.task_id == command.task_id,
                    EffectIntent.run_id == command.run_id,
                    EffectIntent.state.in_(("intent", "outcome_unknown")),
                )
                .limit(2)
            )
        ).all()
    )
    if any(action_id != command.action_id for action_id in unresolved):
        raise ExecutionDeniedError(_DENIED)
    issued = await session.get(EffectIntent, (command.company_id, command.action_id))
    slot = await session.get(NotificationDispatchRow, (command.company_id, parameters.draft_id))
    if issued is not None:
        if slot is None:
            raise ExecutionDeniedError(_DENIED)
        require_issued_binding(work, record.proposal, parameters, issued, slot)
        return await db_now(session)
    if slot is not None or control.paused:
        raise ExecutionDeniedError(_DENIED)
    await require_runtime_scope(
        session, control, scope, credential.identity, allow_inactive=False, owner_read=False
    )
    await require_not_cancelled(session, work.company_id, work.task_id)
    await require_management_execution(
        session,
        control,
        work,
        credential.identity,
        services.reads.facts.catalog,
        services.reads.facts.artifacts,
        services.reads.facts.freshness,
        record.proposal,
        "tool_attempts",
    )
    selection = NativeNotificationSelection(
        company_id=command.company_id,
        draft_id=parameters.draft_id,
        sender_task_id=command.task_id,
        plan=guard.registration.plan,
    )
    prepared = services.reads.guarded(guard).preparation
    current = await current_prepared_admission(
        prepared,
        session,
        control,
        work,
        credential.identity,
        selection,
        guard.registration.sender,
        record,
    )
    await require_effect_authority(
        session, control, work, row.id, await db_now(session), (), scope, credential.identity
    )
    final = await db_now(session)
    if (
        record.approval is None
        or not record.approval.issued_at <= final < record.approval.expires_at
    ):
        raise ExecutionDeniedError(_DENIED)
    current.require_time(services.reads.facts.catalog, final)
    services.reads.drafts.recipients.require_current(current.draft.recipient_policy, final)
    if prepared.operation_guard is None:
        raise ExecutionDeniedError(_DENIED)
    prepared.operation_guard.require_time(final)
    return final


async def prior_live_deadline(
    services: NotificationDispatchWorkerServices,
    scope: LedgerScope,
    credential: AuthenticatedWorkerIdentity,
    guard: NotificationOperationGuard,
    command: SegmentCommand,
) -> datetime | None:
    """Read actual prior server deadline only after complete command/current owner/member checks."""
    services.require_enabled()
    if not isinstance(credential, AuthenticatedWorkerIdentity) or credential is not guard.witness:
        raise ExecutionDeniedError(_DENIED)
    command.require_scope(scope)
    guard.require_identity(credential.identity)
    guard.require_company(command.company_id)
    if (credential.identity.principal_id, credential.identity.workspace_id) != (
        command.actor_id,
        command.workspace_id,
    ):
        raise ExecutionDeniedError(_DENIED)
    async with runtime_transaction(
        services.reads.factory, scope, credential.identity, allow_paused=True, allow_inactive=True
    ) as (session, control, _):
        work = await execution_row(session, scope)
        if (
            control.owner_id != command.actor_id
            or await dispatched_binding(session, work, scope, command.segment_id) != command
        ):
            raise ExecutionDeniedError(_DENIED)
        final = await require_wait_admission(
            session, control, services, scope, credential, guard, command, work
        )
        services.reads.require_registration(guard.snapshot)
        guard.require_time(final)
        if work.worker_id is not None and work.lease_until is not None and work.lease_until > final:
            if work.segment_id != command.segment_id:
                raise ExecutionDeniedError(_DENIED)
            return work.lease_until
        return None


async def require_current_credential(
    services: NotificationDispatchWorkerServices,
    scope: LedgerScope,
    credential: AuthenticatedWorkerIdentity,
    guard: NotificationOperationGuard,
) -> None:
    """Re-read native current member/owner and original window; never fetch another token."""
    async with runtime_transaction(
        services.reads.factory, scope, credential.identity, allow_paused=True, allow_inactive=True
    ) as (session, control, _):
        if control.owner_id != scope.principal_id:
            raise ExecutionDeniedError(_DENIED)
        services.require_enabled()
        services.reads.require_registration(guard.snapshot)
        guard.require_identity(credential.identity)
        guard.require_time(await db_now(session))


async def wait_prior(seconds: float) -> None:
    """Cancellation-aware acquisition wait; no effect or new workflow is issued."""
    await asyncio.sleep(seconds)


async def recover_notification_lease(
    services: NotificationDispatchWorkerServices,
    scope: LedgerScope,
    credential: AuthenticatedWorkerIdentity,
    guard: NotificationOperationGuard,
    command: SegmentCommand,
) -> ExecutionLease:
    """Recover only the same permanent segment, with finite monotonic acquisition allowance."""
    limit = asyncio.timeout(MAX_ACQUISITION_SECONDS)
    try:
        async with limit:
            while True:
                deadline = await prior_live_deadline(services, scope, credential, guard, command)
                if deadline is not None:
                    await wait_prior(1.0)
                    await require_current_credential(services, scope, credential, guard)
                    continue
                try:
                    lease = await services.execution.recover_dispatched(
                        scope,
                        credential.identity,
                        services.worker_id,
                        command.segment_id,
                        ttl_seconds=services.lease_ttl_seconds,
                    )
                except ExecutionDeniedError:
                    if (
                        await prior_live_deadline(services, scope, credential, guard, command)
                        is None
                    ):
                        raise
                    continue
                try:
                    await require_current_credential(services, scope, credential, guard)
                except BaseException:
                    await services.execution.release(lease, credential.identity)
                    raise
                return lease
    except TimeoutError:
        if not limit.expired():
            raise
        raise ExecutionDeniedError(
            "Notification prior lease exceeded bounded acquisition"
        ) from None
