"""Strict digest native references, never owner, source access, registration or send authority."""

from typing import Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, model_validator

from nexus.company.management.base import SHA256, Symbol
from nexus.company.notifications.notification_base import NotificationContract


class NativeDigestBinding(NotificationContract):
    report_id: UUID
    report_snapshot_sha256: SHA256
    registration_sha256: SHA256
    policy_sha256: SHA256
    kind: Literal["daily", "weekly"]
    due_bucket: Symbol
    scheduled_for: AwareDatetime

    @model_validator(mode="after")
    def canonical_window(self) -> Self:
        local = self.scheduled_for.astimezone(ZoneInfo("Asia/Bangkok"))
        if (
            (local.hour, local.minute, local.second, local.microsecond) != (9, 0, 0, 0)
            or (self.kind == "weekly" and local.weekday() != 0)
            or self.due_bucket != f"{self.kind}:{local.date().isoformat()}"
        ):
            raise ValueError("Digest binding requires its exact canonical Bangkok09 bucket")
        return self
