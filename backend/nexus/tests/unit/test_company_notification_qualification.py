"""Pure owner/current-source/final-clock negatives; no native DB lookup is claimed."""

from datetime import timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.access import VerifiedIdentity
from nexus.company.notifications.contracts import NotificationDraft, NotificationPayload
from nexus.company.notifications.qualification import (
    NotificationDeniedError,
    require_current_qualification,
)
from nexus.tests.notification_rule_fixtures import (
    NOW,
    OWNER,
    WORKSPACE,
    declared_draft,
    declared_qualification,
)


def test_final_clock_checks_all_source_and_recipient_deadlines() -> None:
    draft = declared_draft()
    qualified = declared_qualification(draft)
    identity = VerifiedIdentity(principal_id=OWNER, workspace_id=WORKSPACE)
    require_current_qualification(qualified, draft, identity, NOW)
    with pytest.raises(NotificationDeniedError):
        require_current_qualification(qualified, draft, identity, NOW + timedelta(minutes=5))
    with pytest.raises(NotificationDeniedError):
        require_current_qualification(qualified, draft, identity, draft.recipient_policy.expires_at)


@pytest.mark.parametrize(
    "field,value",
    [
        ("membership_active", False),
        ("principal_active", False),
        ("owner_id", UUID(int=99)),
        ("membership_role", "admin"),
    ],
)
def test_owner_role_or_cached_membership_never_substitutes_current_facts(
    field: str, value: object
) -> None:
    draft = declared_draft()
    qualified = declared_qualification(draft)
    changed = qualified.model_copy(
        update={"principal": qualified.principal.model_copy(update={field: value})}
    )
    with pytest.raises(
        NotificationDeniedError, match=r"^Owner notification qualification is unavailable$"
    ):
        require_current_qualification(
            changed, draft, VerifiedIdentity(principal_id=OWNER, workspace_id=WORKSPACE), NOW
        )


def test_owner_has_no_implicit_source_access_or_foreign_identity() -> None:
    draft = declared_draft()
    qualified = declared_qualification(draft)
    identity = VerifiedIdentity(principal_id=OWNER, workspace_id=WORKSPACE)
    for changed in (
        qualified.model_copy(update={"current_resource_ids": ()}),
        qualified.model_copy(update={"recipient_policy_sha256": "c" * 64}),
        qualified.model_copy(update={"company_id": UUID(int=99)}),
    ):
        with pytest.raises(NotificationDeniedError):
            require_current_qualification(changed, draft, identity, NOW)
    with pytest.raises(NotificationDeniedError):
        require_current_qualification(
            qualified, draft, identity.model_copy(update={"workspace_id": UUID(int=90)}), NOW
        )


@pytest.mark.parametrize(
    "mailbox",
    [
        "Owner <owner@example.invalid>",
        "owner@example.invalid,other@example.invalid",
        "owner@example.invalid\r\nBcc:other@example.invalid",
        "a@-example.invalid",
    ],
)
def test_single_plain_mailbox_rejects_headers_or_recipient_lists(mailbox: str) -> None:
    with pytest.raises(ValidationError):
        NotificationPayload(
            sender="system@example.invalid", recipient=mailbox, subject="Fixture", text="Fixture"
        )


def test_draft_hash_and_trigger_and_native_company_are_exact() -> None:
    original = declared_draft()
    for patch in (
        {"payload_sha256": "f" * 64},
        {"trigger_sha256": "f" * 64},
        {"company_id": UUID(int=99)},
    ):
        with pytest.raises(ValidationError):
            NotificationDraft.model_validate(original.model_dump() | patch)
