"""Public ingested immutable source requires its actual registered no-expiry policy."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.report_checker import check_internal_report
from nexus.tests.integration.operating_report_fixture import configured_report, loaded_report
from nexus.tests.integration.test_company_operating_reports import (
    reports_factory as reports_factory,
)


async def test_actual_registered_immutable_source_is_fresh_with_qualified_no_ttl(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_report(reports_factory, tmp_path, source_no_ttl=True)
    assert scenario.policies.policy("fixture.source.v1").freshness_seconds is None
    command = await loaded_report(scenario)
    assert command.snapshot is not None
    assert command.snapshot.citations[0].head.fresh_until is None
    assert check_internal_report(command).verdict == "pass"


async def test_nullable_freshness_cannot_survive_mismatched_current_operator_policy(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_report(reports_factory, tmp_path, source_no_ttl=True)
    original = scenario.policies.policy("fixture.source.v1")
    scenario.policies.values[original.source_symbol] = original.model_copy(
        update={"freshness_seconds": 3600}
    )
    with pytest.raises(ValueError):
        await loaded_report(scenario)
