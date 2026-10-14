"""Declared native notification facts for pure tests; no ledger/permit/source authority."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx

from nexus.company.access import PrincipalAccess
from nexus.company.brain.base import SourceTime
from nexus.company.notifications.contracts import (
    NativeNotificationSignal,
    NotificationDraft,
    NotificationPayload,
    NotificationProvenance,
    OwnerRecipientPolicy,
)
from nexus.company.notifications.policy import trigger_sha256
from nexus.company.notifications.qualification import NotificationQualification

NOW = datetime(2035, 2, 5, 2, tzinfo=UTC)
COMPANY = UUID(int=1)
OWNER = UUID(int=3)
WORKSPACE = UUID(int=2)
PROVIDER_ID = UUID(int=100)


def recipient() -> OwnerRecipientPolicy:
    return OwnerRecipientPolicy(
        company_id=COMPANY,
        owner_id=OWNER,
        policy_id=UUID(int=4),
        version="owner-email.1",
        sender="system@example.invalid",
        recipient="owner@example.invalid",
        registered_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )


def payload() -> NotificationPayload:
    return NotificationPayload(
        sender=recipient().sender,
        recipient=recipient().recipient,
        subject="Owner decision required",
        text="A dated fixture requires a dashboard decision.",
    )


def record_response(
    calls: list[httpx.Request], response: httpx.Response
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response

    return handler


def declared_draft() -> NotificationDraft:
    recipient = OwnerRecipientPolicy(
        company_id=COMPANY,
        owner_id=OWNER,
        policy_id=UUID(int=4),
        version="owner-email.1",
        sender="system@example.invalid",
        recipient="owner@example.invalid",
        registered_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    payload = NotificationPayload(
        sender=recipient.sender,
        recipient=recipient.recipient,
        subject="A fixture decision",
        text="Declared native fixture with no execution authority.",
    )
    signal = NativeNotificationSignal(
        company_id=COMPANY,
        event_ids=(UUID(int=10),),
        subject_id=UUID(int=20),
        kind="decision_required",
        state_sha256="a" * 64,
        source_event=SourceTime(precision="unknown", value=None, basis="fixture"),
        observed_at=NOW,
    )
    return NotificationDraft(
        company_id=COMPANY,
        draft_id=UUID(int=30),
        trigger_sha256=trigger_sha256(signal),
        signal=signal,
        recipient_policy=recipient,
        policy_version="owner-notify.v1",
        template_version="owner-plain.v1",
        payload=payload,
        payload_sha256=payload.sha256,
        provenance=NotificationProvenance(
            company_id=COMPANY,
            required_resource_ids=(UUID(int=50),),
            protection_deadlines=(NOW + timedelta(minutes=5),),
            native_snapshot_sha256="b" * 64,
        ),
        operation_id=UUID(int=31),
        audit_trace_id=UUID(int=32),
        recorded_at=NOW,
    )


def declared_qualification(draft: NotificationDraft) -> NotificationQualification:
    return NotificationQualification(
        company_id=COMPANY,
        principal=PrincipalAccess(
            company_id=COMPANY,
            workspace_id=WORKSPACE,
            principal_id=OWNER,
            owner_id=OWNER,
            membership_role="owner",
            company_active=True,
            workspace_active=True,
            principal_active=True,
            membership_active=True,
        ),
        recipient_policy_sha256=draft.recipient_policy.sha256,
        current_resource_ids=draft.provenance.required_resource_ids,
        protection_deadlines=draft.provenance.protection_deadlines,
        checked_at=NOW,
    )
