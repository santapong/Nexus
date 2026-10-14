"""Conservative declared clock rules; actual native source/permit proof is separate PG work."""

from datetime import timedelta
from typing import Literal

import pytest

from nexus.company.notifications.contracts import NotificationPolicy
from nexus.company.notifications.dispatch_windows import require_dispatch_window
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.tests.notification_digest_rule_fixtures import declared_digest, digest_policy
from nexus.tests.notification_rule_fixtures import NOW, declared_draft


@pytest.mark.parametrize("kind", ["daily", "weekly"])
def test_exact_registered_due_window_accepts_later_same_day(
    kind: Literal["daily", "weekly"],
) -> None:
    require_dispatch_window(declared_digest(kind), digest_policy(), NOW + timedelta(hours=3))


def test_weekly_bucket_is_current_monday_until_next_week_not_current_day() -> None:
    draft = declared_digest("weekly")
    require_dispatch_window(draft, digest_policy(), NOW + timedelta(days=2))
    with pytest.raises(NotificationUnavailableError):
        require_dispatch_window(draft, digest_policy(), NOW + timedelta(days=7))


@pytest.mark.parametrize("kind", ["daily", "weekly"])
def test_before_due_or_naive_clock_cannot_issue(kind: Literal["daily", "weekly"]) -> None:
    for now in (NOW - timedelta(microseconds=1), NOW.replace(tzinfo=None)):
        with pytest.raises(NotificationUnavailableError):
            require_dispatch_window(declared_digest(kind), digest_policy(), now)


def test_daily_bucket_cannot_be_reused_on_next_day() -> None:
    with pytest.raises(NotificationUnavailableError):
        require_dispatch_window(declared_digest("daily"), digest_policy(), NOW + timedelta(days=1))


@pytest.mark.parametrize("kind", ["daily", "weekly"])
@pytest.mark.parametrize("change", ["enabled", "kind_flag", "policy_version", "template_version"])
def test_current_policy_flag_and_complete_hash_are_mandatory(
    kind: Literal["daily", "weekly"], change: str
) -> None:
    update: dict[str, object] = {"enabled": False}
    if change == "kind_flag":
        update = {f"{kind}_digest": False}
    elif change in {"policy_version", "template_version"}:
        update = {"version" if change == "policy_version" else change: "changed.v2"}
    current = digest_policy().model_copy(update=update)
    with pytest.raises(NotificationUnavailableError):
        require_dispatch_window(declared_digest(kind), current, NOW)


def test_inconsistent_typed_draft_copy_is_not_a_native_digest_pin() -> None:
    draft = declared_digest("daily")
    for changed in (
        draft.model_copy(update={"kind": "weekly"}),
        draft.model_copy(update={"due_bucket": "daily:2035-02-06"}),
        draft.model_copy(update={"scheduled_for": NOW + timedelta(days=1)}),
    ):
        with pytest.raises(NotificationUnavailableError):
            require_dispatch_window(changed, digest_policy(), NOW)


def test_routine_clock_and_default_policy_behavior_is_preserved() -> None:
    require_dispatch_window(declared_draft(), NotificationPolicy(), NOW)
