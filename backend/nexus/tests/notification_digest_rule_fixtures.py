"""Typed digest declarations for pure rules only; no native issuance or source authority."""

from typing import Literal
from uuid import UUID

from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.contracts import (
    NativeDigestBinding,
    NotificationDraft,
    NotificationPolicy,
)
from nexus.company.notifications.policy import trigger_sha256
from nexus.tests.notification_rule_fixtures import NOW, declared_draft


def digest_policy() -> NotificationPolicy:
    return NotificationPolicy(enabled=True, daily_digest=True, weekly_digest=True)


def declared_digest(kind: Literal["daily", "weekly"]) -> NotificationDraft:
    base = declared_draft()
    binding = NativeDigestBinding(
        company_id=base.company_id,
        report_id=base.signal.subject_id,
        report_snapshot_sha256="c" * 64,
        registration_sha256="d" * 64,
        policy_sha256=canonical_sha256(digest_policy()),
        kind=kind,
        due_bucket=f"{kind}:2035-02-05",
        scheduled_for=NOW,
    )
    signal = base.signal.model_copy(update={"kind": "digest_due", "digest": binding})
    return NotificationDraft.model_validate_json(
        base.model_copy(
            update={
                "draft_id": UUID(int=400 if kind == "daily" else 401),
                "signal": signal,
                "trigger_sha256": trigger_sha256(signal),
                "kind": kind,
                "due_bucket": binding.due_bucket,
                "scheduled_for": binding.scheduled_for,
            }
        ).model_dump_json()
    )
