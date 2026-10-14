"""Deterministic rules over declared server facts; no effect, clock or model authority."""

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from nexus.company.brain.base import ValueContract
from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.contracts import (
    NativeNotificationSignal,
    NotificationAdmission,
    NotificationPolicy,
)
from nexus.company.notifications.usage_rules import routine_admission

__all__ = ["digest_bucket", "routine_admission", "signal_admission", "trigger_sha256"]

BANGKOK = ZoneInfo("Asia/Bangkok")


class _Trigger(ValueContract):
    company: str
    subject: str
    kind: str
    state_sha256: str
    acceptance_sha256: str | None


def trigger_sha256(signal: NativeNotificationSignal) -> str:
    return canonical_sha256(
        _Trigger(
            company=str(signal.company_id),
            subject=str(signal.subject_id),
            kind=signal.kind,
            state_sha256=signal.state_sha256,
            acceptance_sha256=signal.acceptance.acceptance_sha256 if signal.acceptance else None,
        )
    )


def signal_admission(
    policy: NotificationPolicy,
    signal: NativeNotificationSignal,
    *,
    existing_trigger_sha256: str | None = None,
) -> NotificationAdmission:
    if not policy.enabled:
        return NotificationAdmission(state="blocked", reason="disabled")
    if signal.kind in {"idle", "unchanged", "candidate", "metric_satisfied"}:
        return NotificationAdmission(state="suppressed", reason="idle")
    if signal.kind == "work_accepted" and signal.acceptance is None:
        return NotificationAdmission(state="blocked", reason="acceptance_unavailable")
    if signal.kind == "work_accepted" and signal.subject_id not in policy.major_completion_task_ids:
        return NotificationAdmission(state="suppressed", reason="minor_completion")
    if signal.kind == "digest_due" and (
        signal.digest is None
        or not getattr(policy, f"{signal.digest.kind}_digest")
        or signal.digest.policy_sha256 != canonical_sha256(policy)
    ):
        return NotificationAdmission(state="blocked", reason="invalid_snapshot")
    if existing_trigger_sha256 == trigger_sha256(signal):
        return NotificationAdmission(state="suppressed", reason="coalesced")
    return NotificationAdmission(state="eligible", reason="meaningful")


def digest_bucket(
    policy: NotificationPolicy, now: datetime, kind: Literal["daily", "weekly"]
) -> str | None:
    if now.utcoffset() is None:
        raise ValueError("Digest bucket requires an explicit aware instant")
    if not policy.enabled or not getattr(policy, f"{kind}_digest"):
        return None
    local = now.astimezone(BANGKOK)
    if (local.hour, local.minute, local.second, local.microsecond) != (9, 0, 0, 0):
        return None
    if kind == "weekly" and local.weekday() != 0:
        return None
    return f"{kind}:{local.date().isoformat()}"
