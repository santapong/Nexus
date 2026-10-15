"""Neutral locked family reads preserve separate closed native membership."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from nexus.company.management.revision_store import plan_reference
from nexus.execution import cycle_partition_checks as module
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.tests.unit.cycle_partition_fixture import partition


@pytest.mark.parametrize("index", [5, 6, 7, 8])
async def test_deliverable_family_read_does_not_enable_native_wrapper(
    monkeypatch: pytest.MonkeyPatch, index: int
) -> None:
    item = partition(monkeypatch)
    item.work = item.executions[index]
    item.identity = item.identity.model_copy(update={"principal_id": item.work.actor_id})
    monkeypatch.setattr(
        module, "require_runtime_scope", AsyncMock(return_value=item.directories[index])
    )
    before = deepcopy(
        {key: value for key, value in item.work.__dict__.items() if not key.startswith("_sa_")}
    )
    record = await module.read_current_cycle_family_locked(
        item.session,
        item.control,
        item.work,
        item.identity,
        admission=item.cycle.admission,
        registry=item.cycle.registry,
    )
    assert plan_reference(record) == item.bindings[item.work.task_id].plan
    with pytest.raises(ExecutionDeniedError):
        await module.require_cycle_native_partition(
            item.session,
            item.control,
            item.work,
            item.identity,
            admission=item.cycle.admission,
            registry=item.cycle.registry,
        )
    assert {
        key: value for key, value in item.work.__dict__.items() if not key.startswith("_sa_")
    } == before
    item.session.flush.assert_not_called()
    item.session.commit.assert_not_called()


async def test_neutral_family_read_denies_procedure_root(monkeypatch: pytest.MonkeyPatch) -> None:
    item = partition(monkeypatch)
    root = item.executions[0]
    identity = item.identity.model_copy(update={"principal_id": root.actor_id})
    monkeypatch.setattr(
        module, "require_runtime_scope", AsyncMock(return_value=item.directories[0])
    )
    with pytest.raises(ExecutionDeniedError):
        await module.read_current_cycle_family_locked(
            item.session,
            item.control,
            root,
            identity,
            admission=item.cycle.admission,
            registry=item.cycle.registry,
        )
    item.session.flush.assert_not_called()
