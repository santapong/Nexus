"""Unsupported measurements stay unknown; owner audit while paused grants no work permission."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.control_store import CompanyControls
from nexus.company.management.goal_store import GoalStore
from nexus.company.management.goals import GoalDefinition
from nexus.company.management.governance_models import ManagementGoalRevision
from nexus.company.management.transactions import management_owner_transaction
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_metrics import metrics_factory as metrics_factory
from nexus.tests.metric_fixture import configured_metric


@pytest.mark.parametrize(
    ("recipe", "unit", "reason"),
    (
        ("native.semantic-readiness.v1", "count", "unsupported_recipe"),
        ("native.accepted-report-count.v1", "USD", "unsupported_unit"),
    ),
)
async def test_unsupported_recipe_or_unit_is_unknown_not_zero(
    metrics_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    recipe: str,
    unit: str,
    reason: str,
) -> None:
    case = await configured_metric(metrics_factory, tmp_path, recipe=recipe, unit=unit)
    record = await case.store.observe(control(), identity(OWNER), case.request)
    value = record.snapshot.comparison.value
    assert value.kind == "unknown" and value.reason == reason
    assert record.snapshot.comparison.result == "unknown"
    assert record.snapshot.comparison.baseline.kind == "unknown"


async def test_paused_owner_measurement_is_read_only_and_changed_goal_currentness_is_unknown(
    metrics_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await configured_metric(metrics_factory, tmp_path)
    await CompanyControls(metrics_factory).set_paused_registered(control(), identity(OWNER), True)
    record = await case.store.observe(control(), identity(OWNER), case.request)
    assert record.snapshot.comparison.value.kind == "known"
    assert record.snapshot.comparison.value.value == 0
    await CompanyControls(metrics_factory).set_paused_registered(control(), identity(OWNER), False)
    async with management_owner_transaction(metrics_factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        row = await session.get(ManagementGoalRevision, (COMPANY, case.request.goal.revision_id))
        assert row is not None
        data = GoalDefinition.model_validate_json(row.payload_json)
    changed = data.model_copy(update={"title": "Explicit changed measurement scope"})
    await GoalStore(metrics_factory, case.retriever).publish(
        control().model_copy(update={"operation_id": uuid4(), "trace_id": uuid4()}),
        identity(OWNER),
        changed,
        version="metric-v3",
        expected_revision_id=case.request.goal.revision_id,
    )
    current = await case.store.current(control(), identity(OWNER), record.observation_id)
    assert current is not None and current.snapshot.comparison.value.kind == "unknown"
    assert current.comparison_result == "unknown" and not current.snapshot.sources
