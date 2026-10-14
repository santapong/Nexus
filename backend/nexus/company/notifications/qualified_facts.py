"""Qualified native state for deterministic render; never a caller body or effect permission."""

from nexus.company.brain.native_fact_contracts import NativeEventState
from nexus.company.notifications.native_facts import (
    NativeNotificationFact,
    NotificationUnavailableError,
)


class ObsoleteNotificationFactError(NotificationUnavailableError):
    """An actual persisted native wake has no matching current meaningful state."""


class QualifiedNotificationFact(NativeNotificationFact):
    native_state: NativeEventState
