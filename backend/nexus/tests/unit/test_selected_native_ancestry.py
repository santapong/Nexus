"""Configured native leaves require their actual actor and exact partition; mocked SQL only."""

from unittest.mock import AsyncMock

import pytest

from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.execution import cycle_partition_checks
from nexus.execution.native_profile_checks import (
    require_native_ancestry,
    require_notification_ancestry,
)
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.tests.unit.cycle_catalog_fixture import cycle_catalog
from nexus.tests.unit.cycle_partition_fixture import partition


@pytest.mark.parametrize("index", [3, 4])
async def test_configured_zero_model_native_leaf_uses_actual_finite_partition(
    monkeypatch: pytest.MonkeyPatch,
    index: int,
) -> None:
    item = partition(monkeypatch)
    catalog = cycle_catalog().catalog
    catalog = PlanAdmissionCatalog.model_validate(
        catalog.model_dump() | {"cycle_admission": item.cycle.admission}
    )
    work = item.executions[index]
    identity = item.identity.model_copy(update={"principal_id": work.actor_id})
    item.work, item.identity = work, identity
    monkeypatch.setattr(
        cycle_partition_checks,
        "require_runtime_scope",
        AsyncMock(return_value=item.directories[index]),
    )
    child = item.cycle.admission.slots[index - 1].child
    await require_native_ancestry(
        item.session, work, catalog, child, control=item.control, identity=identity
    )
    work.model_requests_used = 1
    with pytest.raises(ExecutionDeniedError):
        await require_native_ancestry(
            item.session, work, catalog, child, control=item.control, identity=identity
        )


async def test_sender_stays_closed_under_positive_model_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = partition(monkeypatch)
    catalog = PlanAdmissionCatalog.model_validate(
        cycle_catalog().catalog.model_dump() | {"cycle_admission": item.cycle.admission}
    )
    with pytest.raises(ExecutionDeniedError):
        await require_notification_ancestry(
            item.session,
            item.control,
            item.executions[-1],
            catalog,
            item.cycle.admission.slots[-1].child,
        )


async def test_mixed_sender_requires_actual_owner_and_full_current_partition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = partition(monkeypatch)
    catalog = PlanAdmissionCatalog.model_validate(
        cycle_catalog().catalog.model_dump() | {"cycle_admission": item.cycle.admission}
    )
    work, child = item.executions[-1], item.cycle.admission.slots[-1].child
    identity = item.identity.model_copy(update={"principal_id": work.actor_id})
    item.work, item.identity = work, identity
    monkeypatch.setattr(
        cycle_partition_checks,
        "require_runtime_scope",
        AsyncMock(return_value=item.directories[-1]),
    )
    await require_notification_ancestry(
        item.session, item.control, work, catalog, child, identity=identity
    )
    work.model_requests_used = 1
    with pytest.raises(ExecutionDeniedError):
        await require_notification_ancestry(
            item.session, item.control, work, catalog, child, identity=identity
        )
