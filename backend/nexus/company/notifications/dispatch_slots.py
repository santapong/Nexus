"""Permanent slots under the actual M1 company mutex; no task, approval or permit creation."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.notifications.contracts import NotificationDraft, NotificationPolicy
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.dispatch_windows import require_dispatch_window
from nexus.company.notifications.draft_models import NotificationDraftRow
from nexus.company.notifications.ledger_rules import stable_idempotency_key
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import JournalAction


async def reserve_notification_slot(
    session: AsyncSession,
    work: ExecutionWork,
    action: JournalAction,
    draft: NotificationDraft,
    policy: NotificationPolicy,
    identity: VerifiedIdentity,
    now: datetime,
) -> date:
    """Only after current M1/draft checks; its deferred intent FK must commit atomically."""
    require_dispatch_window(draft, policy, now)
    day = now.astimezone(ZoneInfo("Asia/Bangkok")).date()
    await require_slot_capacity(session, draft, policy, day)
    session.add(dispatch_row(work, action, draft, identity, day, now))
    return day


async def require_slot_capacity(
    session: AsyncSession, draft: NotificationDraft, policy: NotificationPolicy, day: date
) -> None:
    query = (
        select(func.count())
        .select_from(NotificationDispatchRow)
        .where(
            NotificationDispatchRow.company_id == draft.company_id,
            NotificationDispatchRow.kind == draft.kind,
        )
    )
    if draft.kind == "routine":
        query = query.where(NotificationDispatchRow.bangkok_day == day)
        cap = policy.routine_per_day
    else:
        query = query.join(
            NotificationDraftRow,
            (NotificationDraftRow.company_id == NotificationDispatchRow.company_id)
            & (NotificationDraftRow.draft_id == NotificationDispatchRow.draft_id),
        ).where(NotificationDraftRow.due_bucket == draft.due_bucket)
        cap = 1
    used = await session.scalar(query)
    if used is None or used >= cap:
        message = (
            "Owner notification daily cap is exhausted"
            if draft.kind == "routine"
            else "Owner notification digest slot is exhausted"
        )
        raise NotificationUnavailableError(message)


def dispatch_row(
    work: ExecutionWork,
    action: JournalAction,
    draft: NotificationDraft,
    identity: VerifiedIdentity,
    day: date,
    now: datetime,
) -> NotificationDispatchRow:
    return NotificationDispatchRow(
        company_id=work.company_id,
        draft_id=draft.draft_id,
        action_id=action.id,
        task_id=work.task_id,
        trace_id=work.trace_id,
        run_id=work.run_id,
        intent_fence=work.fence,
        attempt_kind="tool_attempts",
        proposal_sha256=action.proposal_hash,
        registration_sha256=work.registration_hash,
        payload_sha256=draft.payload_sha256,
        recipient_policy_sha256=draft.recipient_policy.sha256,
        idempotency_key=stable_idempotency_key(work.company_id, draft.draft_id),
        kind=draft.kind,
        bangkok_day=day,
        issued_at=now,
        issued_by=identity.principal_id,
        operation_id=action.id,
        audit_trace_id=work.trace_id,
    )
