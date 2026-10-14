"""History engine observer denies full ORM/private draft SQL before cursor execution."""

import pytest
from sqlalchemy import select

from nexus.company.notifications.draft_models import NotificationDraftRow
from nexus.tests.notification_preserved_history_support import HistoricalSQLBodyGuard


def test_selected_public_pins_allow_but_full_orm_draft_projection_denies() -> None:
    guard = HistoricalSQLBodyGuard()
    guard.inspect_sql(
        str(
            select(
                NotificationDraftRow.payload_sha256,
                NotificationDraftRow.recipient_policy_sha256,
                NotificationDraftRow.kind,
            )
        )
    )
    assert guard.checked == 1 and guard.body_sql_attempts == 0
    with pytest.raises(AssertionError, match="cannot select a private draft body"):
        guard.inspect_sql(str(select(NotificationDraftRow)))
    assert guard.checked == 2 and guard.body_sql_attempts == 1


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM company_notification_drafts",
        "SELECT d.* FROM company_notification_drafts d",
        "WITH d AS (SELECT payload_json FROM company_notification_drafts) SELECT * FROM d",
    ],
)
def test_wildcard_or_private_projection_denies_without_sql_disclosure(statement: str) -> None:
    with pytest.raises(
        AssertionError, match=r"^Historical replay cannot select a private draft body$"
    ):
        HistoricalSQLBodyGuard().inspect_sql(statement)
