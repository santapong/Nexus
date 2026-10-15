"""Closed new roles must retain actual immutable family checks, never permission flags."""

from unittest.mock import AsyncMock

import pytest

from nexus.tests.unit.cycle_prerequisite_fixture import deliverable_case
from nexus.tests.unit.test_cycle_partition_checks import retained


@pytest.mark.parametrize("index", [4, 5, 6, 7])
async def test_four_roles_use_actual_family_and_conserve_all_counters(
    monkeypatch: pytest.MonkeyPatch, index: int
) -> None:
    from nexus.execution.cycle_deliverable_partition import (
        require_cycle_deliverable_partition_locked,
    )

    item = deliverable_case(monkeypatch, index)
    if index in (4, 6):
        item.work.model_requests_used = 1
    before = retained(item)
    result = await require_cycle_deliverable_partition_locked(
        item.session,
        item.control,
        item.work,
        item.identity,
        admission=item.cycle.admission,
        registry=item.cycle.registry,
    )
    assert result.payload == item.cycle.full and retained(item) == before


@pytest.mark.parametrize("index", [0, 1, 2, 3, 8, 9, 10])
async def test_unrelated_roles_do_not_reach_shared_family_seam(
    monkeypatch: pytest.MonkeyPatch, index: int
) -> None:
    from nexus.execution import cycle_deliverable_partition as module

    item = deliverable_case(monkeypatch, index)
    shared = AsyncMock(side_effect=AssertionError("unrelated role reached shared seam"))
    monkeypatch.setattr(module, "read_current_cycle_family_locked", shared)
    with pytest.raises(ValueError):
        await module.require_cycle_deliverable_partition_locked(
            item.session,
            item.control,
            item.work,
            item.identity,
            admission=item.cycle.admission,
            registry=item.cycle.registry,
        )
    shared.assert_not_awaited()


@pytest.mark.parametrize("value", [True, 1.0, "1", -1, 2])
async def test_copied_or_exhausted_model_counter_is_denied(
    monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    from nexus.execution.cycle_deliverable_partition import (
        require_cycle_deliverable_partition_locked,
    )

    item = deliverable_case(monkeypatch)
    item.work.model_requests_used = value  # type: ignore[assignment]
    before = retained(item)
    with pytest.raises(ValueError):
        await require_cycle_deliverable_partition_locked(
            item.session,
            item.control,
            item.work,
            item.identity,
            admission=item.cycle.admission,
            registry=item.cycle.registry,
        )
    assert retained(item) == before
