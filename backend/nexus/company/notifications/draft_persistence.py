"""Exact native draft JSON mirrors; a loaded row never replaces fresh authorization."""

from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.event_store import read_event
from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.draft_models import NotificationDraftRow, NotificationEventLinkRow
from nexus.company.notifications.native_facts import NotificationUnavailableError


def stored_draft(row: NotificationDraftRow) -> NotificationDraft:
    draft = NotificationDraft.model_validate_json(row.record_json)
    if (
        draft.company_id,
        draft.draft_id,
        draft.trigger_sha256,
        draft.payload_sha256,
        draft.recipient_policy.sha256,
        draft.recipient_policy.owner_id,
        canonical_sha256(draft),
    ) != (
        row.company_id,
        row.draft_id,
        row.trigger_sha256,
        row.payload_sha256,
        row.recipient_policy_sha256,
        row.recipient_owner_id,
        row.record_sha256,
    ) or row.payload_json.encode() != draft.payload.wire_bytes():
        raise NotificationUnavailableError("Native notification record is unavailable")
    if (
        row.kind,
        row.subject_kind,
        row.subject_id,
        row.native_state_sha256,
        row.due_bucket,
        row.scheduled_for,
    ) != (
        draft.kind,
        draft_subject_kind(draft),
        draft.signal.subject_id,
        draft.signal.state_sha256,
        draft.due_bucket,
        draft.scheduled_for,
    ):
        raise NotificationUnavailableError("Native notification subject/due mirrors differ")
    return draft


def draft_row(draft: NotificationDraft) -> NotificationDraftRow:
    record = draft.model_dump_json(by_alias=True)
    if len(record.encode()) > 4_194_304:
        raise NotificationUnavailableError("Native notification record exceeds its bound")
    return NotificationDraftRow(
        company_id=draft.company_id,
        draft_id=draft.draft_id,
        kind=draft.kind,
        subject_kind=draft_subject_kind(draft),
        subject_id=draft.signal.subject_id,
        native_state_sha256=draft.signal.state_sha256,
        trigger_sha256=draft.trigger_sha256,
        recipient_class="owner",
        recipient_owner_id=draft.recipient_policy.owner_id,
        recipient_policy_id=draft.recipient_policy.policy_id,
        recipient_policy_version=draft.recipient_policy.version,
        recipient_policy_sha256=draft.recipient_policy.sha256,
        recipient_policy_json=draft.recipient_policy.model_dump_json(by_alias=True),
        policy_version=draft.policy_version,
        template_version=draft.template_version,
        payload_sha256=draft.payload_sha256,
        payload_json=draft.payload.wire_bytes().decode(),
        record_sha256=canonical_sha256(draft),
        record_json=record,
        due_bucket=draft.due_bucket,
        scheduled_for=draft.scheduled_for,
        recorded_by=draft.recipient_policy.owner_id,
        operation_id=draft.operation_id,
        audit_trace_id=draft.audit_trace_id,
        recorded_at=draft.recorded_at,
    )


def draft_subject_kind(
    draft: NotificationDraft,
) -> Literal["action", "work", "company_budget", "work_budget", "digest_report"]:
    if draft.signal.kind == "digest_due":
        return "digest_report"
    if draft.signal.kind == "decision_required":
        return "action"
    if draft.signal.kind == "cap_exhausted":
        return "company_budget" if draft.signal.budget_day is not None else "work_budget"
    return "work"


async def persist_draft_locked(
    session: AsyncSession,
    prepared: NotificationDraft,
    event_id: UUID,
) -> NotificationDraft:
    """Public same-session append/link; authorization and final qualification belong to caller."""
    if not session.in_transaction():
        raise NotificationUnavailableError("Native draft append requires its company transaction")
    row = await session.scalar(
        select(NotificationDraftRow).where(
            NotificationDraftRow.company_id == prepared.company_id,
            NotificationDraftRow.trigger_sha256 == prepared.trigger_sha256,
            NotificationDraftRow.recipient_class == "owner",
        )
    )
    saved = stored_draft(row) if row is not None else prepared
    if row is None:
        session.add(draft_row(saved))
    elif (
        saved.provenance != prepared.provenance
        or saved.recipient_policy != prepared.recipient_policy
    ):
        raise NotificationUnavailableError("Native notification draft requires refresh")
    event = await read_event(session, prepared.company_id, event_id)
    if event is None or event_id not in prepared.signal.event_ids:
        raise NotificationUnavailableError("Native notification event is unavailable")
    link = await session.get(NotificationEventLinkRow, (prepared.company_id, event_id))
    if link is not None and (link.draft_id, link.event_sequence) != (
        saved.draft_id,
        event.sequence,
    ):
        raise NotificationUnavailableError("Native notification event is already linked")
    if link is None:
        session.add(
            NotificationEventLinkRow(
                company_id=saved.company_id,
                event_id=event_id,
                event_sequence=event.sequence,
                draft_id=saved.draft_id,
            )
        )
    await session.flush()
    return saved
