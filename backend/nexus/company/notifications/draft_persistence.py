"""Exact native draft JSON mirrors; a loaded row never replaces fresh authorization."""

from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.draft_models import NotificationDraftRow
from nexus.company.notifications.native_facts import NotificationUnavailableError


def stored_draft(row: NotificationDraftRow) -> NotificationDraft:
    draft = NotificationDraft.model_validate_json(row.record_json)
    if (
        row.kind != "routine"
        or (
            draft.company_id,
            draft.draft_id,
            draft.trigger_sha256,
            draft.payload_sha256,
            draft.recipient_policy.sha256,
            draft.recipient_policy.owner_id,
            canonical_sha256(draft),
        )
        != (
            row.company_id,
            row.draft_id,
            row.trigger_sha256,
            row.payload_sha256,
            row.recipient_policy_sha256,
            row.recipient_owner_id,
            row.record_sha256,
        )
        or row.payload_json.encode() != draft.payload.wire_bytes()
    ):
        raise NotificationUnavailableError("Native notification record is unavailable")
    return draft


def draft_row(draft: NotificationDraft) -> NotificationDraftRow:
    record = draft.model_dump_json(by_alias=True)
    if len(record.encode()) > 4_194_304:
        raise NotificationUnavailableError("Native notification record exceeds its bound")
    return NotificationDraftRow(
        company_id=draft.company_id,
        draft_id=draft.draft_id,
        kind="routine",
        subject_kind="work",
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
        due_bucket=None,
        scheduled_for=None,
        recorded_by=draft.recipient_policy.owner_id,
        operation_id=draft.operation_id,
        audit_trace_id=draft.audit_trace_id,
        recorded_at=draft.recorded_at,
    )
