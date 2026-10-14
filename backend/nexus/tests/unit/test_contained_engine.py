"""Fixed engine subprocess composition is synthetic; no actual Podman invocation."""

from __future__ import annotations

import asyncio
from time import monotonic_ns
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.builder import contained_engine as module


def exact_argv() -> tuple[str, ...]:
    return (*module.INSPECT_PREFIX, module.INSPECT_FORMAT, "a" * 64)


@pytest.mark.parametrize(
    "change",
    ["program", "manager", "operation", "format", "id", "extra", "limit", "deadline"],
)
async def test_arbitrary_inspection_or_expired_deadline_denies_before_spawn(
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    argv = list(exact_argv())
    limit, deadline = 65_536, 2_000_000
    if change == "program":
        argv[0] = "/bin/sh"
    elif change == "manager":
        argv[2] = "--cgroup-manager=systemd"
    elif change == "operation":
        argv[3] = "rm"
    elif change == "format":
        argv[5] = "{{.Config.Env}}"
    elif change == "id":
        argv[-1] = "short"
    elif change == "extra":
        argv.append("another")
    elif change == "limit":
        limit = 65_537
    else:
        deadline = 100_000
    monkeypatch.setattr(module, "clock_us", lambda: 100_000)
    spawn = AsyncMock()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises((ValueError, TimeoutError)):
        await module.ContainedEngineReader().query(tuple(argv), deadline, limit)
    spawn.assert_not_awaited()


def process_with_streams(body: bytes, *, code: int = 0) -> MagicMock:
    process = MagicMock()
    stdout, stderr = asyncio.StreamReader(), asyncio.StreamReader()
    stdout.feed_data(body)
    stdout.feed_eof()
    stderr.feed_eof()
    process.stdout, process.stderr, process.returncode = stdout, stderr, code
    process.wait = AsyncMock(return_value=code)
    return process


async def test_fixed_capture_uses_exact_argv_sanitized_environment_and_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = process_with_streams(b"bounded synthetic JSON")
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(module, "clock_us", lambda: 100_000)
    body = await module.ContainedEngineReader().query(exact_argv(), 2_000_000, 65_536)
    assert body == b"bounded synthetic JSON"
    assert spawn.await_args is not None
    assert spawn.await_args.args == exact_argv()
    assert spawn.await_args.kwargs["stdin"] == asyncio.subprocess.DEVNULL
    assert set(spawn.await_args.kwargs["env"]) == {"PATH", "HOME", "XDG_RUNTIME_DIR", "LANG"}
    process.wait.assert_awaited()
    process.kill.assert_not_called()


async def test_output_overflow_kills_and_reaps_exact_owned_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = process_with_streams(b"x" * 65_537)
    process.returncode = None

    def killed() -> None:
        process.returncode = -9

    process.kill.side_effect = killed
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    monkeypatch.setattr(module, "clock_us", lambda: 100_000)
    with pytest.raises(ValueError, match="output limit"):
        await module.ContainedEngineReader().query(exact_argv(), 2_000_000, 65_536)
    process.kill.assert_called_once()
    process.wait.assert_awaited()


async def test_cancellation_retains_owned_process_reaping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = process_with_streams(b"")
    process.stdout = asyncio.StreamReader()
    process.returncode = None
    waiting = asyncio.Event()

    async def wait() -> int:
        await waiting.wait()
        return -9

    def killed() -> None:
        process.returncode = -9
        waiting.set()

    process.wait = AsyncMock(side_effect=wait)
    process.kill.side_effect = killed
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(module, "clock_us", lambda: 100_000)
    task = asyncio.create_task(
        module.ContainedEngineReader().query(exact_argv(), 2_000_000, 65_536)
    )
    for _ in range(10):
        await asyncio.sleep(0)
        if spawn.await_count:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    process.kill.assert_called_once()
    cast(AsyncMock, process.wait).assert_awaited()


async def test_actual_short_timeout_does_not_replenish_absolute_reaping_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = process_with_streams(b"")
    process.stdout = asyncio.StreamReader()
    process.returncode = None
    stopped = asyncio.Event()

    async def wait() -> int:
        await stopped.wait()
        return -9

    def killed() -> None:
        process.returncode = -9
        stopped.set()

    process.wait = AsyncMock(side_effect=wait)
    process.kill.side_effect = killed
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    deadline = monotonic_ns() // 1000 + 120_000
    with pytest.raises(TimeoutError):
        await module.ContainedEngineReader().query(exact_argv(), deadline, 65_536)
    assert monotonic_ns() // 1000 < deadline
    process.kill.assert_called_once()
    cast(AsyncMock, process.wait).assert_awaited()
