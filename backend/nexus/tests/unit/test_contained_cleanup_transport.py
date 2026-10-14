"""OS engine boundary is entirely mocked; these tests never start Podman or delete a container."""

import asyncio
from typing import cast

import pytest

import nexus.builder.contained_cleanup as module
from nexus.builder.contained_cleanup import (
    CleanupDeadline,
    CleanupUnresolvedError,
    ContainedCleanup,
    cleanup_argv,
)
from nexus.tests.contained_cleanup_fixture import identity, inspection, inventory
from nexus.tests.contained_process_fixture import Process


def child(raw: bytes, *, stopped: bool = True, code: int = 0) -> Process:
    value = Process(stopped=stopped)
    value.stdout = asyncio.StreamReader()
    value.stdout.feed_data(raw)
    value.stdout.feed_eof()
    if stopped:
        value.returncode = code
    return value


def install(
    monkeypatch: pytest.MonkeyPatch, children: list[Process]
) -> tuple[list[tuple[str, ...]], list[int]]:
    calls: list[tuple[str, ...]] = []
    now = [1_000_000]

    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        calls.append(args)
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL
        return cast(asyncio.subprocess.Process, children.pop(0))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(module, "clock_us", lambda: now[0])
    return calls, now


@pytest.mark.asyncio
async def test_inventory_inspect_then_separate_exact_id_remove(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, now = install(
        monkeypatch,
        [child(inventory()), child(inspection()), child(identity().container_id.encode() + b"\n")],
    )
    service = ContainedCleanup()
    deadline = CleanupDeadline.start()
    captured = await service.inspect_stopped(identity(), deadline)
    assert captured.state == "stopped" and captured.inspection is not None
    assert len(calls) == 2  # Inspection never removes standalone.
    result = await service.remove_stopped(captured, deadline)
    assert calls == [cleanup_argv(kind, identity()) for kind in ("inventory", "inspect", "remove")]
    assert (
        result.reaped
        and result.exit_code == 0
        and result.stdout.strip() == identity().container_id.encode()
    )
    assert deadline.started_us == now[0] and deadline.end_us == now[0] + 5_000_000


@pytest.mark.asyncio
async def test_complete_absence_does_not_inspect_or_remove(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, _ = install(monkeypatch, [child(b"")])
    service = ContainedCleanup()
    deadline = CleanupDeadline.start()
    absent = await service.inspect_stopped(identity(), deadline)
    assert absent.state == "absent" and len(calls) == 1
    with pytest.raises(ValueError):
        await service.remove_stopped(absent, deadline)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["inventory", "inspect", "remove"])
async def test_nonzero_never_proves_absence_or_success(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    replies = [child(inventory()), child(inspection()), child(identity().container_id.encode())]
    index = {"inventory": 0, "inspect": 1, "remove": 2}[phase]
    replies[index].returncode = 125
    calls, _ = install(monkeypatch, replies)
    service = ContainedCleanup()
    deadline = CleanupDeadline.start()
    with pytest.raises(CleanupUnresolvedError) as caught:
        capture = await service.inspect_stopped(identity(), deadline)
        await service.remove_stopped(capture, deadline)
    assert len(calls) == index + 1 and caught.value.capture is not None
    assert caught.value.capture.exit_code == 125 and caught.value.capture.reaped


@pytest.mark.asyncio
@pytest.mark.parametrize("splice", ["bytes", "complete"])
async def test_spliced_stopped_capture_never_reaches_rm(
    monkeypatch: pytest.MonkeyPatch, splice: str
) -> None:
    calls, _ = install(monkeypatch, [child(inventory()), child(inspection())])
    service = ContainedCleanup()
    deadline = CleanupDeadline.start()
    captured = await service.inspect_stopped(identity(), deadline)
    assert captured.inspection is not None
    change = {"stdout": b"{}"} if splice == "bytes" else {"complete": False}
    copied = captured.model_copy(
        update={"inspection": captured.inspection.model_copy(update=change)}
    )
    with pytest.raises(ValueError):
        await service.remove_stopped(copied, deadline)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_wrong_rm_stdout_is_preserved_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, _ = install(monkeypatch, [child(inventory()), child(inspection()), child(b"wrong-id\n")])
    service = ContainedCleanup()
    deadline = CleanupDeadline.start()
    captured = await service.inspect_stopped(identity(), deadline)
    with pytest.raises(CleanupUnresolvedError) as caught:
        await service.remove_stopped(captured, deadline)
    assert len(calls) == 3 and caught.value.capture is not None
    assert caught.value.capture.stdout == b"wrong-id\n"


@pytest.mark.asyncio
async def test_shared_budget_expiry_after_inspection_never_removes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, now = install(monkeypatch, [child(inventory()), child(inspection())])
    service = ContainedCleanup()
    deadline = CleanupDeadline.start()
    captured = await service.inspect_stopped(identity(), deadline)
    now[0] = deadline.end_us
    with pytest.raises(TimeoutError):
        await service.remove_stopped(captured, deadline)
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("stream,cap", [("stdout", 65536), ("stderr", 4096)])
async def test_overflow_retains_bounded_prefix_and_reaps(
    monkeypatch: pytest.MonkeyPatch, stream: str, cap: int
) -> None:
    value = child(b"", stopped=False)
    pipe = asyncio.StreamReader()
    pipe.feed_data(b"x" * (cap + 1))
    pipe.feed_eof()
    setattr(value, stream, pipe)
    calls, _ = install(monkeypatch, [value])
    with pytest.raises(CleanupUnresolvedError) as caught:
        await ContainedCleanup().inspect_stopped(identity(), CleanupDeadline.start())
    assert len(calls) == 1 and value.killed and caught.value.capture is not None
    capture = caught.value.capture
    assert getattr(capture, stream) == b"x" * cap and capture.overflow and capture.reaped


@pytest.mark.asyncio
async def test_cancel_before_handle_later_obtained_exact_child_reaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    value = child(b"", stopped=False)
    monkeypatch.setattr(module, "clock_us", lambda: 1_000_000)

    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        entered.set()
        await release.wait()
        return cast(asyncio.subprocess.Process, value)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(
        ContainedCleanup().inspect_stopped(identity(), CleanupDeadline.start())
    )
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(CleanupUnresolvedError) as caught:
        await task
    assert caught.value.capture is not None and caught.value.capture.reaped
    assert value.killed and value.wait_count >= 1


@pytest.mark.asyncio
async def test_cancel_without_handle_retains_pending_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    value = child(b"")
    now = [1_000_000]
    monkeypatch.setattr(module, "clock_us", lambda: now[0])

    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        entered.set()
        await release.wait()
        return cast(asyncio.subprocess.Process, value)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(
        ContainedCleanup().inspect_stopped(identity(), CleanupDeadline.start())
    )
    await entered.wait()
    now[0] = 6_000_000
    task.cancel()
    with pytest.raises(CleanupUnresolvedError) as caught:
        await task
    pending = caught.value.pending
    assert pending is not None and not pending.done() and caught.value.capture is None
    release.set()
    assert await pending is cast(asyncio.subprocess.Process, value)
    assert not value.killed and value.wait_count == 0


@pytest.mark.asyncio
async def test_scheduling_delay_expiry_never_reaches_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, _ = install(monkeypatch, [])
    ticks = iter((1_000_000, 1_000_000, 6_000_001, 6_000_001))
    monkeypatch.setattr(module, "clock_us", lambda: next(ticks))
    deadline = CleanupDeadline(started_us=1_000_000, end_us=6_000_000)
    with pytest.raises(CleanupUnresolvedError):
        await ContainedCleanup().inspect_stopped(identity(), deadline)
    assert calls == []


@pytest.mark.asyncio
async def test_hung_command_uses_remaining_total_and_retains_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = child(b"original bounded prefix", stopped=False)
    calls, _ = install(monkeypatch, [value])
    deadline = CleanupDeadline(started_us=1_000_000, end_us=1_150_000)
    with pytest.raises(CleanupUnresolvedError) as caught:
        await ContainedCleanup().inspect_stopped(identity(), deadline)
    assert len(calls) == 1 and value.killed and caught.value.capture is not None
    assert caught.value.capture.stdout == b"original bounded prefix"
    assert caught.value.capture.reaped


@pytest.mark.asyncio
async def test_unreapable_exact_child_is_retained_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    class Unreaped(Process):
        async def wait(self) -> int:
            await asyncio.Event().wait()
            return -9

    value = Unreaped(stopped=False)
    calls, _ = install(monkeypatch, [value])
    with pytest.raises(CleanupUnresolvedError) as caught:
        await ContainedCleanup().inspect_stopped(
            identity(), CleanupDeadline(started_us=1_000_000, end_us=1_150_000)
        )
    assert calls and caught.value.capture is not None and not caught.value.capture.reaped
    assert caught.value.process is cast(asyncio.subprocess.Process, value)
