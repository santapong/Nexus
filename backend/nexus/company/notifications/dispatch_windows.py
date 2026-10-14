"""Current digest window descriptions; these pure checks never issue effect authority."""

from datetime import datetime

from nexus.company.brain.native_fact_digest import digest_window
from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.contracts import NotificationDraft, NotificationPolicy
from nexus.company.notifications.native_facts import NotificationUnavailableError


def require_dispatch_window(
    draft: NotificationDraft, policy: NotificationPolicy, now: datetime
) -> None:
    """Runtime callers supply the fresh DB clock; routine's existing behavior is preserved."""
    if draft.kind == "routine":
        return
    digest = draft.signal.digest
    if (
        now.utcoffset() is None
        or digest is None
        or not policy.enabled
        or not getattr(policy, f"{draft.kind}_digest", False)
        or digest.policy_sha256 != canonical_sha256(policy)
        or (draft.kind, draft.due_bucket, draft.scheduled_for)
        != (digest.kind, digest.due_bucket, digest.scheduled_for)
    ):
        raise NotificationUnavailableError("Native notification digest window is unavailable")
    current = digest_window(draft.kind, now)
    if current is None or current != (draft.due_bucket, draft.scheduled_for):
        raise NotificationUnavailableError("Native notification digest window is unavailable")
