"""Fixed inspection command is mocked at OS boundary; no Podman/container is launched."""

import asyncio
from typing import cast

import pytest

import nexus.builder.contained_discovery as module
from nexus.builder.contained_discovery import (
    ContainedDiscovery,
    DiscoveryUnavailableError,
    discovery_argv,
)
from nexus.tests.contained_process_fixture import Process, binding, launch
from nexus.tests.unit.test_contained_discovery import body


def pipe(raw: bytes) -> asyncio.StreamReader:
    result = asyncio.StreamReader()
    result.feed_data(raw)
    result.feed_eof()
    return result


def install(monkeypatch: pytest.MonkeyPatch, child: Process) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        calls.append(args)
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL
        return cast(asyncio.subprocess.Process, child)

    monkeypatch.setattr(module, "clock_us", lambda: 12_000_000)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return calls


@pytest.mark.asyncio
async def test_fixed_transport_complete_bytes_exact_argv_and_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Process()
    child.stdout = pipe(body())
    calls = install(monkeypatch, child)
    result = await ContainedDiscovery().discover(launch(), 103, 13_000_000)
    assert calls == [discovery_argv(binding())]
    assert result.container_id == "e" * 64 and result.runtime_pid == 103
    assert child.wait_count >= 1 and not child.killed


@pytest.mark.asyncio
@pytest.mark.parametrize("field,cap", [("stdout", 65536), ("stderr", 4096)])
async def test_transport_output_overflow_reaps_exact_reader(
    monkeypatch: pytest.MonkeyPatch, field: str, cap: int
) -> None:
    child = Process(stopped=False)
    setattr(child, field, pipe(b"x" * (cap + 1)))
    install(monkeypatch, child)
    with pytest.raises(ValueError):
        await ContainedDiscovery().discover(launch(), 103, 13_000_000)
    assert child.killed and child.wait_count >= 1


@pytest.mark.asyncio
async def test_nonzero_is_unavailable_not_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    child = Process()
    child.returncode = 125
    child.stdout = pipe(body())
    install(monkeypatch, child)
    with pytest.raises(DiscoveryUnavailableError):
        await ContainedDiscovery().discover(launch(), 103, 13_000_000)


@pytest.mark.asyncio
async def test_cancel_owned_inspect_drains_and_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    child = Process(stopped=False)
    calls = install(monkeypatch, child)
    task = asyncio.create_task(ContainedDiscovery().discover(launch(), 103, 13_000_000))
    while not calls:
        await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert child.killed and child.wait_count >= 1


@pytest.mark.asyncio
async def test_expired_shared_end_never_starts_inspection(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch, Process())
    with pytest.raises(TimeoutError):
        await ContainedDiscovery().discover(launch(), 103, 12_050_000)
    assert calls == []
