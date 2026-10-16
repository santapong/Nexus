"""Actual retirement owns shared C/L/owner/cost leaves before engine disposal."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from dbos import DBOS
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.execution.coding_application_runtime import (
    retire_coding_application,
    start_coding_application_worker,
)
from nexus.tests.unit.coding_application_fixture import application


@pytest.mark.parametrize("resource", ["model", "input", "candidate", "cost", "metadata"])
async def test_real_unfinished_leaf_survives_repeated_shutdown_cancellation(
    tmp_path: Path, resource: str
) -> None:
    value = application(tmp_path)
    entered, finish = asyncio.Event(), asyncio.Event()
    events = []

    async def leaf() -> None:
        entered.set()
        await finish.wait()

    owner = asyncio.create_task(leaf())
    assert value.planning.cycle_costs is not None
    owners = {
        "model": value.services.evidence._owners,
        "input": value.reads._owners,
        "candidate": value.lifecycle.candidates._owners,
        "cost": value.planning.cycle_costs.reads.models._owners,
        "metadata": value.lifecycle._owners,
    }
    owners[resource].append(owner)
    await entered.wait()

    async def destroy() -> None:
        events.append("destroy")

    async def dispose() -> None:
        events.append("dispose")

    retirement = asyncio.create_task(
        retire_coding_application(value, destroy=destroy, dispose=dispose)
    )
    await asyncio.sleep(0)
    retirement.cancel()
    await asyncio.sleep(0)
    retirement.cancel()
    assert not retirement.done() and not events and not owner.done()
    finish.set()
    await retirement
    assert events == ["destroy", "dispose"]


@pytest.mark.parametrize("other", ["planning", "coding"])
async def test_dedicated_worker_denies_any_preconfigured_l_or_c_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, other: str
) -> None:
    from nexus.execution import coding_worker, planning_worker

    value = application(tmp_path)
    monkeypatch.setattr(planning_worker, "_services", None)
    monkeypatch.setattr(coding_worker, "_services", None)
    if other == "planning":
        monkeypatch.setattr(planning_worker, "_services", value.planning.runtime)
    else:
        monkeypatch.setattr(coding_worker, "_services", value.services)
    with pytest.raises(ValueError, match="separate previously unconfigured"):
        await start_coding_application_worker(value, "unused-unit-url")


@pytest.mark.parametrize("partial", [False, True])
async def test_real_c_launcher_uses_pinned_one_shot_queue_and_owned_partial_retirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, partial: bool
) -> None:
    """Real C launcher and pinned listen API; SDK instance/SQL/launch/register are supplied.

    Cohesion exception: one complete launch/partial-cleanup sequence retains
    the unchanged decisive one-shot SDK selector and original host executor.
    """
    import dbos._dbos as sdk_module

    from nexus.execution import coding_worker, planning_worker

    @dataclass
    class SuppliedSDKState:
        _launched: bool = False
        _listening_queues: list[str] | None = None

    value, state, events = application(tmp_path), SuppliedSDKState(), []
    monkeypatch.setattr(sdk_module, "_dbos_global_instance", state)
    monkeypatch.setattr(planning_worker, "_services", None)
    monkeypatch.setattr(coding_worker, "_services", None)
    sql = AsyncMock(return_value=False)
    monkeypatch.setattr(AsyncSession, "scalar", sql)

    def configure(actual: object, url: str) -> None:
        assert actual is value.services and url == "unused-unit-url"
        coding_worker._services = value.services
        events.append("configure")

    def launch() -> None:
        assert state._listening_queues == ["nexus.coding"]
        state._launched = True
        events.append("sdk.launch")

    def destroy(*, workflow_completion_timeout_sec: int) -> None:
        assert workflow_completion_timeout_sec == 1
        events.append("sdk.destroy")

    registered = AsyncMock(side_effect=ValueError("queue-registration") if partial else None)
    monkeypatch.setattr(coding_worker, "configure_coding_worker", configure)
    monkeypatch.setattr(DBOS, "launch", launch)
    monkeypatch.setattr(DBOS, "destroy", destroy)
    monkeypatch.setattr(DBOS, "register_queue_async", registered)
    # Unchanged installed DBOS.listen_queues rejects a second selector invocation.
    if partial:
        with pytest.raises(ValueError, match="queue-registration"):
            await start_coding_application_worker(value, "unused-unit-url")
    else:
        runtime = await start_coding_application_worker(value, "unused-unit-url")
        await runtime.destroy()
    assert state._listening_queues == ["nexus.coding"] and state._launched
    assert events == ["configure", "sdk.launch", "sdk.destroy"]
    assert await asyncio.to_thread(lambda: "host filesystem executor available")
    sql.assert_awaited_once()
    registered.assert_awaited_once_with(
        "nexus.coding", global_concurrency=1, worker_concurrency=1, polling_interval_sec=1.0
    )
