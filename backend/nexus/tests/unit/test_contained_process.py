"""Pure spawn-order harness; no OS scope/container/DB/SDK execution."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from nexus.builder.contained_contracts import ParentObservation, ScopeExpectation
from nexus.builder.contained_evidence_types import ObservationDeadline
from nexus.builder.contained_process import ContainedProcess, ProcessOwnershipUnresolvedError
from nexus.builder.contained_process_contracts import (
    PreparedContainedLaunch,
    ProcessRunBinding,
    require_spawn_ready,
)
from nexus.builder.contained_spawn_window import SpawnWindow
from nexus.tests.contained_process_fixture import Process, binding, launch, parent, window


class Watch:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def before_spawn(self) -> SpawnWindow:
        self.events.append("watch")
        return window()

    async def check(self) -> None:
        self.events.append("watch-check")


class Parents:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def observe(self, expected: ScopeExpectation) -> ParentObservation:
        self.events.append("parent")
        return parent()


@pytest.mark.asyncio
async def test_expiry_after_last_parent_read_spawns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    async def forbidden(*args: object, **kwargs: object) -> asyncio.subprocess.Process:
        pytest.fail("Expired final source/lease window reached spawn")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    process = ContainedProcess(
        Parents(events),
        clock_us=iter((12_000_000, 13_000_001)).__next__,
        utc_now=lambda: datetime(2026, 10, 15, tzinfo=UTC) + timedelta(seconds=1),
    )
    with pytest.raises(ValueError):
        await process.start(
            launch(),
            binding(),
            parent().expectation,
            Watch(events),
            ObservationDeadline(end_us=13_000_000),
        )
    assert events == ["watch", "parent"]


@pytest.mark.asyncio
async def test_exact_watch_parent_check_then_spawn_without_intervening_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.builder.contained_process as module

    events: list[str] = []
    real = require_spawn_ready

    def check(
        value: PreparedContainedLaunch,
        bound: ProcessRunBinding,
        observed: ParentObservation,
        checked: SpawnWindow,
        *,
        monotonic_now_us: int,
        utc_now: datetime,
    ) -> None:
        events.append("sync")
        real(value, bound, observed, checked, monotonic_now_us=monotonic_now_us, utc_now=utc_now)

    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        events.append("spawn")
        assert args == launch().argv
        return cast(asyncio.subprocess.Process, Process())

    monkeypatch.setattr(module, "require_spawn_ready", check)
    monkeypatch.setattr(module, "_proc", lambda _: (7770, parent().kernel.cgroup_path))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    driver = ContainedProcess(
        Parents(events),
        clock_us=lambda: 12_020_000,
        utc_now=lambda: datetime(2026, 10, 15, tzinfo=UTC) + timedelta(milliseconds=20),
    )
    result = await driver.start(
        launch(),
        binding(),
        parent().expectation,
        Watch(events),
        ObservationDeadline(end_us=13_000_000),
    )
    assert events == ["watch", "parent", "sync", "spawn"]
    assert result.runtime_start_ticks == 7770


def driver(events: list[str], *, clock: Callable[[], int] = lambda: 12_020_000) -> ContainedProcess:
    return ContainedProcess(
        Parents(events),
        clock_us=clock,
        utc_now=lambda: datetime(2026, 10, 15, tzinfo=UTC) + timedelta(milliseconds=20),
    )


@pytest.mark.asyncio
async def test_descriptor_cpu_crosses_window_before_spawn_denies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.builder.contained_process as module

    ticks = [12_020_000]
    real = require_spawn_ready

    def costly(
        value: PreparedContainedLaunch,
        bound: ProcessRunBinding,
        observed: ParentObservation,
        checked: SpawnWindow,
        *,
        monotonic_now_us: int,
        utc_now: datetime,
    ) -> None:
        real(value, bound, observed, checked, monotonic_now_us=monotonic_now_us, utc_now=utc_now)
        ticks[0] = 13_000_001

    async def forbidden(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        pytest.fail("Late CPU descriptor validation reached spawn")

    monkeypatch.setattr(module, "require_spawn_ready", costly)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    with pytest.raises(ValueError):
        await driver([], clock=lambda: ticks[0]).start(
            launch(),
            binding(),
            parent().expectation,
            Watch([]),
            ObservationDeadline(end_us=13_000_000),
        )


@pytest.mark.asyncio
async def test_scheduled_spawn_rechecks_window_after_other_ready_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.builder.contained_process as module

    ticks = [12_020_000]
    real = require_spawn_ready

    def checked(
        value: PreparedContainedLaunch,
        bound: ProcessRunBinding,
        observed: ParentObservation,
        checked: SpawnWindow,
        *,
        monotonic_now_us: int,
        utc_now: datetime,
    ) -> None:
        real(value, bound, observed, checked, monotonic_now_us=monotonic_now_us, utc_now=utc_now)
        asyncio.get_running_loop().call_soon(lambda: ticks.__setitem__(0, 13_000_001))

    calls = 0

    async def forbidden(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        nonlocal calls
        calls += 1
        return cast(asyncio.subprocess.Process, Process())

    monkeypatch.setattr(module, "require_spawn_ready", checked)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    with pytest.raises(ValueError, match="expired"):
        await driver([], clock=lambda: ticks[0]).start(
            launch(),
            binding(),
            parent().expectation,
            Watch([]),
            ObservationDeadline(end_us=13_000_000),
        )
    assert calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["watch", "parent"])
async def test_stalled_pre_spawn_reads_share_original_end(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    ready = asyncio.Event()

    class BlockedWatch(Watch):
        async def before_spawn(self) -> SpawnWindow:
            await ready.wait()
            return window()

    class BlockedParents(Parents):
        async def observe(self, expected: ScopeExpectation) -> ParentObservation:
            await ready.wait()
            return parent()

    async def forbidden(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        pytest.fail("Blocked authority/parent read reached spawn")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    value = ContainedProcess(
        BlockedParents([]) if phase == "parent" else Parents([]),
        clock_us=lambda: 12_850_000,
        utc_now=lambda: datetime(2026, 10, 15, tzinfo=UTC) + timedelta(milliseconds=850),
    )
    with pytest.raises(TimeoutError):
        await value.start(
            launch(),
            binding(),
            parent().expectation,
            BlockedWatch([]) if phase == "watch" else Watch([]),
            ObservationDeadline(end_us=13_000_000),
        )


@pytest.mark.asyncio
async def test_cancel_before_spawn_handle_obtains_and_reaps_exact_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nexus.builder.contained_process as module

    entered, release = asyncio.Event(), asyncio.Event()
    child = Process(stopped=False)

    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        entered.set()
        await release.wait()
        return cast(asyncio.subprocess.Process, child)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(module, "_proc", lambda _: (7770, parent().kernel.cgroup_path))
    task = asyncio.create_task(
        driver([]).start(
            launch(),
            binding(),
            parent().expectation,
            Watch([]),
            ObservationDeadline(end_us=13_000_000),
        )
    )
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert child.killed and child.wait_count == 1


@pytest.mark.asyncio
async def test_cancel_before_handle_deadline_retains_strong_unknown_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    child = Process()
    clock = [12_020_000]

    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        entered.set()
        await release.wait()
        return cast(asyncio.subprocess.Process, child)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(
        driver([], clock=lambda: clock[0]).start(
            launch(),
            binding(),
            parent().expectation,
            Watch([]),
            ObservationDeadline(end_us=13_000_000),
        )
    )
    await entered.wait()
    clock[0] = 13_000_000
    task.cancel()
    with pytest.raises(ProcessOwnershipUnresolvedError) as caught:
        await task
    pending = caught.value.pending
    assert pending is not None and not pending.done()
    release.set()
    assert await pending is cast(asyncio.subprocess.Process, child)
    assert (
        not child.killed and child.wait_count == 0
    )  # Unknown is retained, never fabricated cleanup.


@pytest.mark.asyncio
async def test_cancel_after_handle_before_pid_read_reaps_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()
    child = Process(stopped=False)

    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        return cast(asyncio.subprocess.Process, child)

    async def slow_proc(call: Callable[[int], tuple[int, str]], pid: int) -> tuple[int, str]:
        entered.set()
        await asyncio.Event().wait()
        return (7770, parent().kernel.cgroup_path)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(asyncio, "to_thread", slow_proc)
    task = asyncio.create_task(
        driver([]).start(
            launch(),
            binding(),
            parent().expectation,
            Watch([]),
            ObservationDeadline(end_us=13_000_000),
        )
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert child.killed and child.wait_count == 1
