"""Exact governed L composite at actual begin; native context/allowance SQL is supplied."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nexus.company.management.planning_intent import PlanningIntentCheck
from nexus.harness.model_intent import ModelIntentCheck
from nexus.tests.unit.nexus_intent_fixture import boundary
from nexus.tests.unit.nexus_planning_fixture import planning_check


async def test_real_planner_model_composite_can_issue_only_its_model_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = boundary(0)
    effects = value.install(monkeypatch)
    checks = await planning_check(value, effects, tmp_path)
    # Existing native context/goal SQL delivery is supplied, not a native acceptance claim.
    monkeypatch.setattr(PlanningIntentCheck, "validate", AsyncMock())
    monkeypatch.setattr(ModelIntentCheck, "_require_caps", AsyncMock())
    result = await effects.begin(
        value.lease, value.identity, value.action.id, kind="model_requests", before_intent=checks
    )
    assert result.permit_external_call and value.work.model_requests_used == 1
    assert value.work.tool_attempts_used == 0 and len(value.added) == 2
