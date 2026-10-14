"""Resolved native facts and deterministic owner text; no completion/effect promotion."""

from datetime import datetime
from uuid import uuid5

from pydantic import Field

from nexus.company.access import CompanyControlScope
from nexus.company.management.base import Name, require_company
from nexus.company.notifications.contracts import (
    NativeNotificationSignal,
    NotificationContract,
    NotificationDraft,
    NotificationPayload,
    NotificationPolicy,
    NotificationProvenance,
    OwnerRecipientPolicy,
)
from nexus.company.notifications.policy import signal_admission, trigger_sha256


class NotificationUnavailableError(ValueError):
    """Required native notification configuration/facts cannot currently produce a draft."""


class NativeNotificationFact(NotificationContract):
    signal: NativeNotificationSignal
    work_title: Name
    provenance: NotificationProvenance
    details: tuple[Name, ...] = Field(default=(), max_length=8)


def render_native_draft(
    scope: CompanyControlScope,
    policy: NotificationPolicy,
    recipient: OwnerRecipientPolicy,
    fact: NativeNotificationFact,
    now: datetime,
) -> NotificationDraft:
    require_company(scope.company_id, recipient, fact, fact.signal, fact.provenance)
    if signal_admission(policy, fact.signal).state != "eligible":
        raise NotificationUnavailableError("Native notification is not currently eligible")
    headers = {
        "work_accepted": "Independent work acceptance recorded",
        "failed": "Work failed",
    }
    if fact.signal.kind not in headers:
        raise NotificationUnavailableError("Native notification event is unsupported")
    payload = _payload(recipient, fact, now)
    trigger = trigger_sha256(fact.signal)
    return NotificationDraft(
        company_id=scope.company_id,
        draft_id=uuid5(scope.company_id, f"owner-notify:{trigger}"),
        trigger_sha256=trigger,
        signal=fact.signal,
        recipient_policy=recipient,
        policy_version=policy.version,
        template_version=policy.template_version,
        payload=payload,
        payload_sha256=payload.sha256,
        provenance=fact.provenance,
        operation_id=scope.operation_id,
        audit_trace_id=scope.trace_id,
        recorded_at=now,
    )


def _payload(
    recipient: OwnerRecipientPolicy, fact: NativeNotificationFact, now: datetime
) -> NotificationPayload:
    subject = (
        "Work failed" if fact.signal.kind == "failed" else "Independent work acceptance recorded"
    )
    source = fact.signal.source_event
    dated = source.value if source.value is not None else "unknown"
    text = "\n".join(
        (
            subject,
            f"Work: {fact.work_title}",
            f"Native subject: {fact.signal.subject_id}",
            f"Source date ({source.precision}): {dated}",
            f"Observed: {now.isoformat()}",
            *fact.details,
            "Open the authenticated company dashboard to inspect or decide.",
            "This message grants no approval, budget or execution authority.",
        )
    )
    return NotificationPayload(
        sender=recipient.sender, recipient=recipient.recipient, subject=subject, text=text
    )
