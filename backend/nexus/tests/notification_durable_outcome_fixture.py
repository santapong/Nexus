"""TEST-only exact two fresh outcome DBs; original accepted DB is never selected."""

from collections.abc import AsyncIterator

import pytest

from nexus.tests.notification_durable_pg_fixture import (
    DurableFixtureDatabase,
    DurableNotificationEnvironment,
    durable_notification_database_scope,
)


def outcome_database(outcome: str) -> DurableFixtureDatabase:
    """No accepted rerun, alias or caller DB is allowed by the new outcome fixture."""
    if outcome == "rejected":
        return "nexus_company_test_notification_durable_rejected"
    if outcome == "unknown":
        return "nexus_company_test_notification_durable_unknown"
    raise ValueError("Fresh notification outcome fixture is unavailable")


@pytest.fixture
async def durable_outcome_environment(
    outcome: str,
) -> AsyncIterator[DurableNotificationEnvironment]:
    async with durable_notification_database_scope(outcome_database(outcome)) as environment:
        yield environment
