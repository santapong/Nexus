"""Explicit optional owner inbox dependencies; no default sender, transport or activation."""

from __future__ import annotations

from dataclasses import dataclass

from nexus.company.access import CompanyDirectory
from nexus.company.notifications.inbox_store import NotificationInboxStore


@dataclass(frozen=True, slots=True)
class NotificationApiServices:
    directory: CompanyDirectory
    inbox: NotificationInboxStore | None = None
