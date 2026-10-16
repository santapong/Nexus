"""Finite child/pipe ownership and clocks; every engine issue is a supplied mock."""

import asyncio
from pathlib import Path
from typing import cast

import pytest

import nexus.builder.contained_owned_stop_io as module
from nexus.builder.contained_owned_stop_io import OwnedStopIO, StopIOUnresolvedError
from nexus.tests.contained_process_fixture import Process, binding
from nexus.tests.unit.test_contained_owned_stop import owned


def spawn_mock(monkeypatch: pytest.MonkeyPatch, child: Process) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    async def spawn(*argv: str, **kwargs: object) -> asyncio.subprocess.Process:
        calls.append(argv)
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL
        assert kwargs["stdout"] == kwargs["stderr"] == asyncio.subprocess.PIPE
        assert kwargs["env"] == {}
        return cast(asyncio.subprocess.Process, child)

    monkeypatch.setattr(module, "engine_environment", lambda: {})
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return calls


def reply(body: bytes, stderr: bytes = b"", *, code: int = 0) -> Process:
    child = Process()
    child.returncode = code
    child.stdout = asyncio.StreamReader()
    child.stdout.feed_data(body)
    child.stdout.feed_eof()
    child.stderr = asyncio.StreamReader()
    child.stderr.feed_data(stderr)
    child.stderr.feed_eof()
    return child


async def test_actual_io_captures_complete_reply_and_reaps_fixed_id_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    item, context, started = await owned(monkeypatch, tmp_path)
    child = reply(b"137\n")
    calls = spawn_mock(monkeypatch, child)
    io = OwnedStopIO(clock=lambda: 12_020_000)
    try:
        result = await io.call("wait", context, started, binding(), 13_000_000)
        assert result.stdout == b"137\n" and result.complete and result.reaped
        assert result.exit_code == 0 and result.stderr == b"" and not result.overflow
        assert calls == [(*module.STOP_PREFIX, "wait", context.seal.container.container_id)]
        assert child.wait_count == 1 and not child.killed
    finally:
        item.owner.close()


@pytest.mark.parametrize("remaining", [0, 1, 99_999, 100_000])
async def test_expired_or_reserved_timer_tail_issues_no_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, remaining: int
) -> None:
    item, context, started = await owned(monkeypatch, tmp_path)
    calls = spawn_mock(monkeypatch, reply(b"0\n"))
    io = OwnedStopIO(clock=lambda: 13_000_000 - remaining)
    try:
        with pytest.raises(TimeoutError):
            await io.call("wait", context, started, binding(), 13_000_000)
        assert calls == []
    finally:
        item.owner.close()


@pytest.mark.parametrize(
    ("body", "stderr", "code", "overflow"),
    [
        (b"x" * 65537, b"", 0, True),
        (b"0\n", b"x" * 4097, 0, True),
        (b"0\n", b"diagnostic", 0, False),
        (b"0\n", b"", 1, False),
    ],
)
async def test_overflow_stderr_and_nonzero_keep_bounded_complete_or_partial_owners(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    body: bytes,
    stderr: bytes,
    code: int,
    overflow: bool,
) -> None:
    item, context, started = await owned(monkeypatch, tmp_path)
    calls = spawn_mock(monkeypatch, reply(body, stderr, code=code))
    io = OwnedStopIO(clock=lambda: 12_020_000)
    try:
        with pytest.raises(StopIOUnresolvedError) as caught:
            await io.call("inspect", context, started, binding(), 13_000_000)
        error = caught.value
        assert len(calls) == 1 and error.owners.settled()
        assert error.capture is not None and error.capture.reaped
        assert len(error.capture.stdout) <= 65536 and len(error.capture.stderr) <= 4096
        assert error.capture.overflow is overflow
        assert all(row.done() and not row.cancelled() for row in error.owners.readers)
    finally:
        item.owner.close()


async def test_scheduled_issue_revalidates_original_end_before_spawning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    item, context, started = await owned(monkeypatch, tmp_path)
    calls = spawn_mock(monkeypatch, reply(b"0\n"))
    now = [12_020_000]
    io = OwnedStopIO(clock=lambda: now[0])
    actual = io.remaining
    count = 0

    def remaining(end: int, reserve: int = 0) -> float:
        nonlocal count
        count += 1
        # Initial admission and enclosing timeout pass. Scheduled issue is fresh.
        if count == 3:
            now[0] = end
        return actual(end, reserve)

    monkeypatch.setattr(io, "remaining", remaining)
    try:
        with pytest.raises(StopIOUnresolvedError) as caught:
            await io.call("wait", context, started, binding(), 13_000_000)
        assert calls == [] and caught.value.owners.pending.done()
        assert not caught.value.owners.pending.cancelled()
        assert caught.value.capture is None
    finally:
        item.owner.close()


async def test_terminal_reply_after_original_end_is_retained_without_adoption(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    item, context, started = await owned(monkeypatch, tmp_path)
    child = reply(b"0\n")
    calls = spawn_mock(monkeypatch, child)
    now = [12_020_000]
    original = child.wait

    async def late_wait() -> int:
        result = await original()
        now[0] = 13_000_000
        return result

    monkeypatch.setattr(child, "wait", late_wait)
    try:
        with pytest.raises(StopIOUnresolvedError) as caught:
            await OwnedStopIO(clock=lambda: now[0]).call(
                "wait", context, started, binding(), 13_000_000
            )
        assert len(calls) == 1 and caught.value.owners.settled()
        assert caught.value.capture is not None
        assert caught.value.capture.stdout == b"0\n"
    finally:
        item.owner.close()


async def test_repeated_cancellation_preserves_first_exception_and_actual_pipe_wait_owners(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    item, context, started = await owned(monkeypatch, tmp_path)
    child = Process(stopped=False)
    child.stdout, child.stderr = asyncio.StreamReader(), asyncio.StreamReader()
    killed = asyncio.Event()

    def kill() -> None:
        child.killed = True
        killed.set()  # Actual wait/EOF deliberately remain pending until finite release.

    monkeypatch.setattr(child, "kill", kill)
    calls = spawn_mock(monkeypatch, child)
    task = asyncio.create_task(
        OwnedStopIO(clock=lambda: 12_020_000).call("wait", context, started, binding(), 13_000_000)
    )
    retained = None
    try:
        while child.wait_count == 0:
            await asyncio.sleep(0)
        task.cancel("first cancellation")
        await killed.wait()
        task.cancel("second cancellation")
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        assert caught.value.args == ("first cancellation",)
        retained = caught.value.__dict__["_nexus_owned_stop_io"]
        assert isinstance(retained, StopIOUnresolvedError)
        assert not retained.owners.settled() and len(calls) == 1
        assert len(retained.owners.readers) == 3
        assert all(not row.cancelled() for row in retained.owners.readers)
        assert any(not row.done() for row in retained.owners.readers)
    finally:
        child.stdout.feed_eof()
        child.stderr.feed_eof()
        child.returncode = -9
        child.done.set()
        if retained is not None:
            await asyncio.gather(*retained.owners.readers, return_exceptions=True)
            assert retained.owners.retirement is not None
            await retained.owners.retirement
            assert retained.owners.settled()
        await asyncio.gather(task, return_exceptions=True)
        item.owner.close()


async def test_cancelled_pending_spawn_retains_real_task_and_late_child_without_new_issue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    item, context, started = await owned(monkeypatch, tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    child = reply(b"0\n")
    calls = 0
    now = [12_020_000]

    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return cast(asyncio.subprocess.Process, child)

    monkeypatch.setattr(module, "engine_environment", lambda: {})
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(
        OwnedStopIO(clock=lambda: now[0]).call("wait", context, started, binding(), 13_000_000)
    )
    try:
        await entered.wait()
        now[0] = 13_000_000
        task.cancel("original cancellation")
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        retained = caught.value.__dict__["_nexus_owned_stop_io"]
        assert isinstance(retained, StopIOUnresolvedError)
        assert not retained.owners.pending.done() and not retained.owners.pending.cancelled()
        assert retained.owners.process is None and retained.capture is None
        assert retained.owners.retirement is not None and not retained.owners.retirement.done()
        release.set()
        assert await retained.owners.pending is cast(asyncio.subprocess.Process, child)
        await retained.owners.retirement
        assert calls == 1 and retained.owners.settled() and retained.capture is None
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        item.owner.close()


async def test_late_actual_spawn_is_aborted_drained_and_reaped_without_late_adoption(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    item, context, started = await owned(monkeypatch, tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    child = Process(stopped=False)
    child.stdout, child.stderr = asyncio.StreamReader(), asyncio.StreamReader()
    now = [12_020_000]
    calls = 0

    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return cast(asyncio.subprocess.Process, child)

    monkeypatch.setattr(module, "engine_environment", lambda: {})
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(
        OwnedStopIO(clock=lambda: now[0]).call("inspect", context, started, binding(), 13_000_000)
    )
    retained = None
    try:
        await entered.wait()
        now[0] = 13_000_000
        task.cancel("original cancellation")
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        retained = caught.value.__dict__["_nexus_owned_stop_io"]
        assert isinstance(retained, StopIOUnresolvedError) and retained.capture is None
        release.set()
        assert await retained.owners.pending is cast(asyncio.subprocess.Process, child)
        for _ in range(20):
            if child.wait_count:
                break
            await asyncio.sleep(0)
        assert child.killed and child.wait_count > 0, "Late actual CLI has no abort/reap owner"
        assert retained.owners.process is cast(asyncio.subprocess.Process, child)
        assert len(retained.owners.readers) == 3 and not retained.owners.settled()
        retirement = retained.owners.retirement
        assert retirement is not None and not retirement.done() and not retirement.cancelled()
        child.stdout.feed_eof()
        child.stderr.feed_eof()
        await retirement
        assert retained.owners.settled() and retained.capture is None and calls == 1
        assert caught.value.args == ("original cancellation",)
    finally:
        release.set()
        child.kill()
        child.stdout.feed_eof()
        child.stderr.feed_eof()
        await asyncio.gather(task, return_exceptions=True)
        if retained is not None:
            await asyncio.gather(
                retained.owners.pending, *retained.owners.readers, return_exceptions=True
            )
            retirement = getattr(retained.owners, "retirement", None)
            if isinstance(retirement, asyncio.Future):
                await retirement
        item.owner.close()
