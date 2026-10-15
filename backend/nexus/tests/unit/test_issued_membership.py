"""Opaque live-context mechanics over real temporary FDs and mocked proc metadata."""

import asyncio
import os
import threading
from pathlib import Path
from typing import cast

import pytest

from nexus.builder.contained_discovery_seal import FixedDiscoverySeal
from nexus.builder.contained_issued_context import OwnedIssuedContext
from nexus.tests.contained_process_fixture import binding
from nexus.tests.issued_membership_fixture import fixed_seal, prepared


async def test_actual_owned_context_binds_distinct_processes_and_held_runtime_leaf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    item = await prepared(monkeypatch, tmp_path)
    try:
        receipt = await fixed_seal(monkeypatch)
        context = item.owner.seal(receipt)
        item.migrate()
        value = await context.observe(item.parent.expectation, item.kernel, 13_000_000)
        assert value.collector_pid == os.getpid() and value.runtime_pid == 777
        assert value.collector_start_ticks == 1111 and value.runtime_start_ticks == 7770
        assert value.runtime_inode == item.leaf.stat().st_ino
        assert value.scope_inode == item.root.stat().st_ino and item.owner.identity == value
        assert await context.observe(item.parent.expectation, item.kernel, 13_000_000) == value
    finally:
        assert item.owner.close()


async def test_portable_container_or_caller_key_cannot_enable_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    item = await prepared(monkeypatch, tmp_path)
    try:
        receipt = await fixed_seal(monkeypatch)
        with pytest.raises(ValueError):
            item.owner.seal(cast(FixedDiscoverySeal, receipt.container))
        with pytest.raises(TypeError):
            OwnedIssuedContext(object(), item.owner, receipt)
        with pytest.raises(TypeError):
            FixedDiscoverySeal(object(), receipt.container, binding(), 777, b"caller JSON")
    finally:
        item.owner.close()


@pytest.mark.parametrize("suffix", ["", "/runtime2", "/runtime/x", "/elsewhere/runtime"])
async def test_only_exact_postseal_runtime_leaf_is_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, suffix: str
) -> None:
    item = await prepared(monkeypatch, tmp_path)
    try:
        context = item.owner.seal(await fixed_seal(monkeypatch))
        path = item.parent.expectation.cgroup_path + suffix
        item.proc[os.getpid()], item.proc[777] = (1111, path), (7770, path)
        with pytest.raises(ValueError, match="exact runtime leaf"):
            await context.observe(item.parent.expectation, item.kernel, 13_000_000)
    finally:
        item.owner.close()


@pytest.mark.parametrize("variation", ["collector_reused", "runtime_reused", "runtime_exited"])
async def test_owned_process_start_reuse_or_terminal_handle_never_qualifies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, variation: str
) -> None:
    item = await prepared(monkeypatch, tmp_path)
    try:
        context = item.owner.seal(await fixed_seal(monkeypatch))
        item.migrate()
        if variation == "runtime_exited":
            item.transport.kill()
        else:
            pid = os.getpid() if variation == "collector_reused" else 777
            item.proc[pid] = (9999, item.proc[pid][1])
        with pytest.raises(ValueError):
            await context.observe(item.parent.expectation, item.kernel, 13_000_000)
    finally:
        item.owner.close()


@pytest.mark.parametrize("variation", ["root", "leaf", "symlink"])
async def test_replaced_or_symlinked_directory_never_reuses_held_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, variation: str
) -> None:
    item = await prepared(monkeypatch, tmp_path)
    try:
        context = item.owner.seal(await fixed_seal(monkeypatch))
        item.migrate()
        await context.observe(item.parent.expectation, item.kernel, 13_000_000)
        target = item.root if variation == "root" else item.leaf
        retained = target.with_name(target.name + "-retained")
        target.rename(retained)
        if variation == "symlink":
            target.symlink_to(retained, target_is_directory=True)
        else:
            target.mkdir()
        with pytest.raises((ValueError, OSError)):
            await context.observe(item.parent.expectation, item.kernel, 13_000_000)
    finally:
        item.owner.close()


async def test_wrong_job_and_closed_context_deny_without_new_io(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from uuid import UUID

    item = await prepared(monkeypatch, tmp_path)
    context = item.owner.seal(await fixed_seal(monkeypatch))
    try:
        with pytest.raises(ValueError, match="another original job"):
            await context.observe(
                item.parent.expectation.model_copy(update={"task_id": UUID(int=9)}),
                item.kernel,
                13_000_000,
            )
        assert item.owner.close()
        with pytest.raises(ValueError, match="closed"):
            await context.observe(item.parent.expectation, item.kernel, 13_000_000)
    finally:
        item.owner.close()


async def test_cancel_keeps_pending_worker_owned_and_local_fds_until_it_returns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import nexus.builder.contained_issued_context as module

    item = await prepared(monkeypatch, tmp_path)
    context = item.owner.seal(await fixed_seal(monkeypatch))
    item.migrate()
    entered, release = threading.Event(), threading.Event()

    def real(pid: int) -> tuple[int, str]:
        return item.proc[pid]

    def blocked(pid: int) -> tuple[int, str]:
        entered.set()
        if not release.wait(2):
            raise TimeoutError("Finite nominated test worker")
        return real(pid)

    monkeypatch.setattr(module, "_proc", blocked)
    task = asyncio.create_task(context.observe(item.parent.expectation, item.kernel, 13_000_000))
    try:
        async with asyncio.timeout(1):
            while not entered.is_set():
                await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not item.owner.close()
        assert item.owner._pending and item.owner._root_fd is None
    finally:
        release.set()
        await asyncio.gather(*tuple(item.owner._pending), return_exceptions=True)
        assert item.owner.close() and item.owner._leaf_fd is None
