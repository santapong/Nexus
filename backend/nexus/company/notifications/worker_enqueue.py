"""Exact owner decision consumption, held cost and public durable enqueue commit together."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.management.native_profile_admission import ledger_scope
from nexus.company.management.plans import RunBinding
from nexus.company.management.scheduling_projection import projection
from nexus.company.management.scheduling_queue import enqueue_candidate
from nexus.company.management.scheduling_reads import inspect_task
from nexus.company.management.scheduling_support import SchedulerServices, SchedulingCandidate
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.managed_admission import (
    ManagedNotificationAdmission,
    notification_action_id,
)
from nexus.company.notifications.managed_contracts import NativeNotificationSelection
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.worker_authorization import current_prepared_admission
from nexus.company.notifications.worker_config import WorkerRegistrationSnapshot
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.effect_support import require_effect_authority
from nexus.execution.notification_worker_contracts import NotificationEnqueueResult
from nexus.execution.notification_worker_services import NotificationDispatchWorkerServices
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_recovery import dispatched_binding
from nexus.execution.runtime_support import db_now, execution_row, runtime_transaction
from nexus.harness.canonical import action_hash
from nexus.harness.journal_authorization import authorize_registered_pending_locked
from nexus.harness.journal_contracts import ActionRecord
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.journal_submission import pending_action_record

_UNAVAILABLE = "Notification targeted enqueue is unavailable"


@dataclass(frozen=True, slots=True)
class SealedNotificationSchedulerIdentity:
    """One verified process witness narrows scheduler identity; current native gates still apply."""

    binding: RunBinding
    credential: AuthenticatedWorkerIdentity

    def actor(self, binding: RunBinding) -> VerifiedIdentity:
        """Return only the sealed configured sender identity; native permission is separate."""
        if not isinstance(self.credential, AuthenticatedWorkerIdentity) or binding != self.binding:
            raise NotificationUnavailableError(_UNAVAILABLE)
        identity = self.credential.identity
        if (identity.principal_id, identity.workspace_id) != (
            binding.actor_id,
            binding.workspace_id,
        ):
            raise NotificationUnavailableError(_UNAVAILABLE)
        self.credential.require_time(datetime.now(UTC))
        return identity


async def require_only_authorized_unissued_action(
    session: AsyncSession,
    work: ExecutionWork,
    action_id: UUID,
) -> None:
    """Count every authorized candidate before existing-dispatch replay can hide a conflict."""
    actual = tuple(
        (
            await session.scalars(
                select(JournalAction.id)
                .where(
                    JournalAction.company_id == work.company_id,
                    JournalAction.task_id == work.task_id,
                    JournalAction.trace_id == work.trace_id,
                    JournalAction.state == "authorized",
                    JournalAction.consumed_at.is_not(None),
                    JournalAction.id.not_in(
                        select(EffectIntent.action_id).where(
                            EffectIntent.company_id == work.company_id,
                        )
                    ),
                )
                .limit(2),
            )
        ).all()
    )
    if actual != (action_id,):
        raise NotificationUnavailableError(_UNAVAILABLE)


async def _unissued_action(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    selection: NativeNotificationSelection,
    binding: RunBinding,
) -> tuple[JournalAction, ActionRecord]:
    if (
        binding.actor_id != control.owner_id
        or work.worker_id is not None
        or work.lease_until is not None
        or work.state not in {"eligible", "awaiting_approval"}
    ):
        raise NotificationUnavailableError(_UNAVAILABLE)
    action_id = notification_action_id(selection.plan, binding.task_id, selection.draft_id)
    if work.waiting_action_id is not None and work.waiting_action_id != action_id:
        raise NotificationUnavailableError(_UNAVAILABLE)
    row = await session.get(JournalAction, action_id)
    issued = await session.get(EffectIntent, (work.company_id, action_id))
    slot = await session.get(NotificationDispatchRow, (work.company_id, selection.draft_id))
    unresolved = await session.scalar(
        select(EffectIntent.action_id)
        .where(
            EffectIntent.company_id == work.company_id,
            EffectIntent.task_id == work.task_id,
            EffectIntent.state.in_(("intent", "outcome_unknown")),
        )
        .limit(1)
    )
    if row is None or issued is not None or slot is not None or unresolved is not None:
        raise NotificationUnavailableError(_UNAVAILABLE)
    record = pending_action_record(row)
    if record.approval is None or record.proposal_hash != action_hash(record.proposal):
        raise NotificationUnavailableError(_UNAVAILABLE)
    return row, record


def _command_from_queue(
    binding: RunBinding,
    action_id: UUID,
    segment_id: UUID | None,
) -> SegmentCommand:
    if segment_id is None:
        raise NotificationUnavailableError(_UNAVAILABLE)
    return SegmentCommand(
        company_id=binding.company_id,
        task_id=binding.task_id,
        trace_id=binding.trace_id,
        actor_id=binding.actor_id,
        workspace_id=binding.workspace_id,
        run_id=binding.run_id,
        action_id=action_id,
        segment_id=segment_id,
    )


async def _candidate(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
    row: JournalAction,
    admitted: ManagedNotificationAdmission,
    identity: VerifiedIdentity,
    scheduler: SchedulerServices,
) -> SchedulingCandidate:
    current = await inspect_task(session, control, work, identity, scheduler)
    if current.binding != admitted.binding:
        raise NotificationUnavailableError(_UNAVAILABLE)
    if current.projection.eligibility.state == "eligible":
        if current.action is not row or current.identity != identity:
            raise NotificationUnavailableError(_UNAVAILABLE)
        return current
    if (
        current.projection.dispatch != "existing"
        or current.projection.action_id != row.id
        or current.projection.eligibility.state != "waiting"
        or current.projection.eligibility.reason != "dispatch_active"
    ):
        raise NotificationUnavailableError(_UNAVAILABLE)
    # Existing-dispatch metadata is not authority: unchanged public enqueue_candidate
    # repeats real current effect/source/capacity and exact native/DBOS binding checks.
    return SchedulingCandidate(
        work,
        admitted.binding,
        projection(work, admitted.binding, "eligible", "ready"),
        row,
        identity,
        ledger_scope(admitted.binding.child.binding),
    )


def _require_final_time(
    services: NotificationDispatchWorkerServices,
    guard: NotificationOperationGuard,
    first: ManagedNotificationAdmission,
    final: ManagedNotificationAdmission,
    record: ActionRecord,
    now: datetime,
) -> None:
    services.require_enabled()
    services.reads.require_registration(guard.snapshot)
    guard.require_time(now)
    first.require_time(services.reads.facts.catalog, now)
    final.require_time(services.reads.facts.catalog, now)
    services.reads.drafts.recipients.require_current(final.draft.recipient_policy, now)
    approval = record.approval
    if approval is None or not approval.issued_at <= now < approval.expires_at:
        raise NotificationUnavailableError(_UNAVAILABLE)


async def authorize_and_enqueue_prepared_notification(
    services: NotificationDispatchWorkerServices,
    selection: NativeNotificationSelection,
    credential: AuthenticatedWorkerIdentity,
    snapshot: WorkerRegistrationSnapshot,
) -> NotificationEnqueueResult:
    """Enqueue one exact unissued owner action atomically; queue identity never authorizes POST."""
    # Keep this cohesive >50-line CC transaction together: hold, permanent dispatch,
    # DBOS insert/readback and final authority/window failure must roll back together.
    services.require_enabled()
    selection = NativeNotificationSelection.model_validate_json(selection.model_dump_json())
    guard = NotificationOperationGuard(credential, snapshot, services.reads.registrations)
    services.reads.require_registration(snapshot)
    binding = guard.registration.sender
    if (selection.company_id, selection.sender_task_id, selection.plan) != (
        binding.company_id,
        binding.task_id,
        guard.registration.plan,
    ):
        raise NotificationUnavailableError(_UNAVAILABLE)
    prepared = services.reads.guarded(guard).preparation
    scheduler = replace(
        services.scheduler, identities=SealedNotificationSchedulerIdentity(binding, credential)
    )
    identity, scope = credential.identity, ledger_scope(binding)
    async with (
        asyncio.timeout(30),
        runtime_transaction(services.reads.factory, scope, identity) as (session, control, _),
    ):
        work = await execution_row(session, scope)
        row, record = await _unissued_action(session, control, work, selection, binding)
        first = await current_prepared_admission(
            prepared, session, control, work, identity, selection, binding, record
        )
        guard.require_time(await db_now(session))
        approved = await authorize_registered_pending_locked(
            session, control, scope, identity, row.id, await db_now(session), ()
        )
        await session.flush()
        await require_only_authorized_unissued_action(session, work, row.id)
        admitted = await current_prepared_admission(
            prepared, session, control, work, identity, selection, binding, approved
        )
        previous = await session.get(SegmentDispatch, (binding.company_id, row.id))
        candidate = await _candidate(session, control, work, row, admitted, identity, scheduler)
        queued = await enqueue_candidate(session, control, candidate, scheduler)
        command = _command_from_queue(binding, row.id, queued.segment_id)
        actual = await dispatched_binding(session, work, scope, command.segment_id)
        if (
            actual != command
            or queued.workflow_id != actual.workflow_id
            or queued.action_id != row.id
            or queued.dispatch != "enqueued"
        ):
            raise NotificationUnavailableError(_UNAVAILABLE)
        final = await current_prepared_admission(
            prepared, session, control, work, identity, selection, binding, approved
        )
        await require_effect_authority(
            session, control, work, row.id, await db_now(session), (), scope, identity
        )
        now = await db_now(session)
        _require_final_time(services, guard, first, final, approved, now)
        if prepared.operation_guard is None:
            raise NotificationUnavailableError(_UNAVAILABLE)
        prepared.operation_guard.require_time(now)
        return NotificationEnqueueResult(
            company_id=binding.company_id,
            command=actual,
            disposition="existing" if previous is not None else "enqueued",
            observed_at=now,
        )
