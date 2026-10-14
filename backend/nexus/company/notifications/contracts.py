"""Immutable notification declarations; values never issue delivery or approval authority."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import (
    AwareDatetime,
    BeforeValidator,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from nexus.company.brain.base import Count, Flag, Ordinal, exact_count
from nexus.company.brain.sources import ArtifactRevisionRef, SourceHead
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.base import SHA256, SourceTime, Symbol, ValueContract, require_company
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plans import RunBinding

Mailbox = Annotated[str, StringConstraints(min_length=3, max_length=254)]
IdempotencyKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,256}$")]


class NotificationContract(ValueContract):
    schema_version: Literal["nexus.company.notification.v1"] = "nexus.company.notification.v1"
    company_id: UUID


def require_mailbox(value: str) -> str:
    """Narrow plain ASCII address: no display names, header injection or recipient lists."""
    if not re.fullmatch(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", value):
        raise ValueError("A single plain configured mailbox is required")
    local, domain = value.split("@")
    if len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in value:
        raise ValueError("Configured mailbox has an invalid component")
    if any(
        not part or len(part) > 63 or part.startswith("-") or part.endswith("-")
        for part in domain.split(".")
    ):
        raise ValueError("Configured mailbox has an invalid domain")
    return value


class OwnerRecipientPolicy(NotificationContract):
    """Declared server configuration; actual directory/policy lookup remains mandatory."""

    policy_id: UUID
    owner_id: UUID
    version: Symbol
    sender: Mailbox
    recipient: Mailbox
    registered_at: AwareDatetime
    expires_at: AwareDatetime

    _mailboxes = field_validator("sender", "recipient")(require_mailbox)

    @model_validator(mode="after")
    def finite_registration(self) -> Self:
        if self.expires_at <= self.registered_at:
            raise ValueError("Recipient registration requires a finite future deadline")
        return self

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


class NotificationPolicy(ValueContract):
    version: Symbol = "owner-notify.v1"
    template_version: Symbol = "owner-plain.v1"
    enabled: Flag = False
    daily_digest: Flag = False
    weekly_digest: Flag = False
    major_completion_task_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    routine_per_day: Annotated[int, BeforeValidator(exact_count), Field(ge=1, le=10)] = 10

    @model_validator(mode="after")
    def exact_major_selection(self) -> Self:
        if len(set(self.major_completion_task_ids)) != len(self.major_completion_task_ids):
            raise ValueError("Major work notification selection must be unique")
        return self


class CurrentWorkAcceptance(NotificationContract):
    """Resolved native facts declaration; the resolver must recheck actual protected proof."""

    acceptance: WorkAcceptance

    @model_validator(mode="after")
    def exact_work(self) -> Self:
        require_company(self.company_id, self.acceptance)
        if self.acceptance.verdict != "pass":
            raise ValueError("Current accepted work requires exact native independent pass shape")
        return self

    @property
    def work(self) -> RunBinding:
        return self.acceptance.target.author

    @property
    def acceptance_sha256(self) -> str:
        return canonical_sha256(self.acceptance)


SignalKind = Literal[
    "decision_required",
    "blocked",
    "failed",
    "cap_exhausted",
    "work_accepted",
    "idle",
    "unchanged",
    "candidate",
    "metric_satisfied",
]


class NativeNotificationSignal(NotificationContract):
    """Trusted resolver input, never a caller-produced meaningfulness assertion."""

    event_ids: tuple[UUID, ...] = Field(min_length=1, max_length=32)
    subject_id: UUID
    kind: SignalKind
    state_sha256: SHA256
    source_event: SourceTime
    observed_at: AwareDatetime
    acceptance: CurrentWorkAcceptance | None = None

    @model_validator(mode="after")
    def exact_subject(self) -> Self:
        require_company(self.company_id, self.acceptance)
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("Notification event identities must be unique")
        if self.acceptance is not None and (
            self.kind != "work_accepted" or self.subject_id != self.acceptance.work.task_id
        ):
            raise ValueError("Acceptance must bind the exact notified native work")
        return self


class NotificationPayload(ValueContract):
    sender: Mailbox
    recipient: Mailbox
    subject: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    text: Annotated[str, StringConstraints(min_length=1, max_length=32_000)]

    _mailboxes = field_validator("sender", "recipient")(require_mailbox)

    @model_validator(mode="after")
    def bounded_plain_content(self) -> Self:
        if "\r" in self.subject or "\n" in self.subject or "\x00" in self.subject + self.text:
            raise ValueError("Notification contains invalid header/content bytes")
        if len(self.wire_bytes()) > 131_072:
            raise ValueError("Notification payload exceeds the bounded UTF8 envelope")
        return self

    def wire_bytes(self) -> bytes:
        return json.dumps(
            {
                "from": self.sender,
                "to": [self.recipient],
                "subject": self.subject,
                "text": self.text,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.wire_bytes()).hexdigest()


class NotificationProvenance(NotificationContract):
    required_resource_ids: tuple[UUID, ...] = Field(default=(), max_length=6400)
    artifacts: tuple[ArtifactRevisionRef, ...] = Field(default=(), max_length=100)
    source_heads: tuple[SourceHead, ...] = Field(default=(), max_length=6400)
    protection_deadlines: tuple[AwareDatetime, ...] = Field(default=(), max_length=12_800)
    native_snapshot_sha256: SHA256

    @model_validator(mode="after")
    def exact_provenance(self) -> Self:
        require_company(self.company_id, *self.artifacts, *self.source_heads)
        if len(set(self.required_resource_ids)) != len(self.required_resource_ids):
            raise ValueError("Notification resource identities must be unique")
        if len({item.artifact_revision_id for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("Notification artifact revisions must be unique")
        return self


class NotificationDraft(NotificationContract):
    draft_id: UUID
    trigger_sha256: SHA256
    signal: NativeNotificationSignal
    recipient_class: Literal["owner"] = "owner"
    recipient_policy: OwnerRecipientPolicy
    policy_version: Symbol
    template_version: Symbol
    payload: NotificationPayload
    payload_sha256: SHA256
    provenance: NotificationProvenance
    operation_id: UUID
    audit_trace_id: UUID
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def exact_draft(self) -> Self:
        from nexus.company.notifications.policy import trigger_sha256

        require_company(self.company_id, self.signal, self.recipient_policy, self.provenance)
        if (
            self.trigger_sha256 != trigger_sha256(self.signal)
            or self.payload_sha256 != self.payload.sha256
            or (self.payload.sender, self.payload.recipient)
            != (self.recipient_policy.sender, self.recipient_policy.recipient)
        ):
            raise ValueError("Draft differs from its exact registered payload")
        return self


class NotificationEventLink(NotificationContract):
    event_id: UUID
    event_sequence: Count
    draft_id: UUID
    recorded_at: AwareDatetime


class NotificationAttempt(NotificationContract):
    """Exact permanent M1 binding; decoding it is not an external-call permit."""

    draft_id: UUID
    action_id: UUID
    work: RunBinding
    proposal_sha256: SHA256
    payload_sha256: SHA256
    recipient_policy_sha256: SHA256
    intent_fence: Count
    attempt_number: Annotated[Literal[1], BeforeValidator(exact_count)] = 1
    idempotency_key: IdempotencyKey
    kind: Literal["routine", "daily", "weekly"]
    bangkok_day: date
    issued_at: AwareDatetime

    @model_validator(mode="after")
    def exact_attempt(self) -> Self:
        from nexus.company.notifications.ledger_rules import stable_idempotency_key

        require_company(self.company_id, self.work)
        if type(self.attempt_number) is not int:
            raise ValueError("An external notification has one exact integer attempt")
        if self.bangkok_day != self.issued_at.astimezone(ZoneInfo("Asia/Bangkok")).date() or (
            self.idempotency_key != stable_idempotency_key(self.company_id, self.draft_id)
        ):
            raise ValueError("Notification intent differs from its permanent key/effect day")
        return self


class NotificationAdmission(ValueContract):
    state: Literal["eligible", "suppressed", "blocked"]
    reason: Literal[
        "meaningful",
        "disabled",
        "idle",
        "coalesced",
        "acceptance_unavailable",
        "daily_cap",
        "invalid_snapshot",
        "recipient_policy",
        "source_unavailable",
        "minor_completion",
    ]
    routine_slots_used: Ordinal = 0
