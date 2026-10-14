"""Fresh outcome fixtures have a closed DB mapping and preserve the original default wire."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from nexus.settings import settings
from nexus.tests import notification_durable_pg_fixture as module
from nexus.tests.notification_durable_outcome_fixture import outcome_database

_PREFIX = "postgresql+asyncpg://santapong@/"
_QUERY = "?host=/tmp/nexus-release-tests-2026-10-13/socket&port=55438"


def test_original_default_database_wire_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "company_test_database_url",
        _PREFIX + "nexus_company_test_notification_enqueue_atomic" + _QUERY,
    )
    assert (
        module.qualified_durable_url().database == "nexus_company_test_notification_enqueue_atomic"
    )


@pytest.mark.parametrize("invalid", ["foreign_database", "accepted", 1, None])
async def test_foreign_or_untyped_database_denies_before_any_engine_or_migration(
    invalid: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = MagicMock()
    monkeypatch.setattr(module, "create_async_engine", engine)
    with pytest.raises(ValueError):
        async with module.durable_notification_database_scope(invalid):
            raise AssertionError("Invalid DB cannot enter setup")
    engine.assert_not_called()


@pytest.mark.parametrize("outcome", ["accepted", "foreign", ""])
def test_new_outcome_map_cannot_select_original_or_foreign_database(outcome: str) -> None:
    with pytest.raises(ValueError, match="Fresh notification outcome fixture is unavailable"):
        outcome_database(outcome)
