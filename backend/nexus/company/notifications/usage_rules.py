"""Bangkok routine slots count unique actual intent declarations, including unknown sends."""

from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime

from nexus.company.management.base import SHA256
from nexus.company.notifications.contracts import (
    NotificationAdmission,
    NotificationContract,
    NotificationPolicy,
)


class RoutineIntentFact(NotificationContract):
    """Native intent projection, not a caller count, outcome or permission."""

    action_id: UUID
    draft_id: UUID
    payload_sha256: SHA256
    kind: Literal["routine", "daily", "weekly"]
    issued_at: AwareDatetime


def routine_admission(
    policy: NotificationPolicy,
    company_id: UUID,
    now: datetime,
    issued: tuple[RoutineIntentFact, ...],
) -> NotificationAdmission:
    if not policy.enabled:
        return NotificationAdmission(state="blocked", reason="disabled")
    invalid = NotificationAdmission(state="blocked", reason="invalid_snapshot")
    if now.utcoffset() is None or len(issued) > 10_000:
        return invalid
    by_action: dict[UUID, RoutineIntentFact] = {}
    by_draft: dict[UUID, UUID] = {}
    for item in issued:
        if (
            item.company_id != company_id
            or item.issued_at > now
            or (item.action_id in by_action and by_action[item.action_id] != item)
            or (item.draft_id in by_draft and by_draft[item.draft_id] != item.action_id)
        ):
            return invalid
        by_action[item.action_id], by_draft[item.draft_id] = item, item.action_id
    zone = ZoneInfo("Asia/Bangkok")
    day = now.astimezone(zone).date()
    used = sum(
        item.kind == "routine" and item.issued_at.astimezone(zone).date() == day
        for item in by_action.values()
    )
    return NotificationAdmission(
        state="blocked" if used >= policy.routine_per_day else "eligible",
        reason="daily_cap" if used >= policy.routine_per_day else "meaningful",
        routine_slots_used=used,
    )
