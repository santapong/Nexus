"""Actual run lifecycle over opaque fixture owners and ordinary FDs; no engine/scope/DB."""

import asyncio
from pathlib import Path
from typing import cast

import pytest

import nexus.builder.contained_process as module
from nexus.builder.contained_evidence_types import ObservationDeadline
from nexus.builder.contained_process import ContainedProcess
from nexus.builder.contained_process_contracts import (
    PreparedContainedLaunch,
    ProcessSampling,
    StartedContainedProcess,
)
from nexus.company.management.cancellation_support import WorkCancelledError
from nexus.tests.contained_process_fixture import binding, launch, window
from nexus.tests.issued_membership_fixture import fixed_seal, prepared
from nexus.tests.unit.test_contained_process import Watch, driver


async def test_real_run_stops_owned_container_before_cli_and_context_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    item = await prepared(monkeypatch, cast(Path, tmp_path))
    context = item.owner.seal(await fixed_seal(monkeypatch))
    events: list[str] = []
    first = WorkCancelledError("supplied original denial")
    original_close, original_kill = item.owner.close, item.transport.kill

    def close() -> bool:
        events.append("context-close")
        return original_close()

    def kill() -> None:
        events.append("cli-kill")
        original_kill()

    monkeypatch.setattr(item.owner, "close", close)
    monkeypatch.setattr(item.transport, "kill", kill)
    monkeypatch.setattr(module, "_proc", lambda _: (7770, item.parent.kernel.cgroup_path))
    started = StartedContainedProcess(
        item.process,
        item.parent,
        window(),
        7770,
        item.parent.kernel.cgroup_path,
        "observed_path",
        item.owner,
    )

    async def start(*args: object, **kwargs: object) -> StartedContainedProcess:
        return started

    async def monitor(
        self: ContainedProcess,
        current: StartedContainedProcess,
        selected: PreparedContainedLaunch,
        expected: object,
        watch: Watch,
        deadline: ObservationDeadline,
        observer: object,
        state: ProcessSampling,
    ) -> None:
        state.sealed, state.issued_context, state.phase = context.seal.container, context, "watch"
        await watch.check()

    class Denied(Watch):
        async def check(self) -> None:
            raise first

    class Stopper:
        async def stop(self, *args: object) -> None:
            assert args == (context, started, binding(), ObservationDeadline(end_us=13_000_000))
            assert item.owner._closed is False
            events.append("owned-stop")

    value = driver([])
    monkeypatch.setattr(value, "start", start)
    monkeypatch.setattr(value, "stopper", Stopper(), raising=False)
    monkeypatch.setattr(ContainedProcess, "_monitor", monitor)
    try:
        result = await value.run(
            launch(),
            binding(),
            item.parent.expectation,
            Denied([]),
            ObservationDeadline(end_us=13_000_000),
            stdout_limit=1024,
            stderr_limit=1024,
        )
        assert events == ["owned-stop", "cli-kill", "context-close"]
        assert result.capture.interruption == "WorkCancelledError"
        assert result.runtime.reap == "waited" and result.infrastructure == "unresolved"
    finally:
        if item.process.returncode is None:
            original_kill()
        await item.process.wait()
        original_close()


@pytest.mark.parametrize("sealed", [True, False])
@pytest.mark.parametrize("close_failure", [True, False])
async def test_stop_failure_or_unsealed_branch_preserves_first_and_settles_before_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object, sealed: bool, close_failure: bool
) -> None:
    from nexus.builder.contained_owned_stop import ContainedOwnedStop
    from nexus.builder.contained_owned_stop_lifecycle import finish_owned_cleanup

    item = await prepared(monkeypatch, cast(Path, tmp_path))
    context = item.owner.seal(await fixed_seal(monkeypatch))
    first, stop_failure = ValueError("original guard"), ValueError("stop uncertain")
    assert item.process.stdout is not None and item.process.stderr is not None
    state = ProcessSampling(
        asyncio.create_task(item.process.stdout.read()),
        asyncio.create_task(item.process.stderr.read()),
        asyncio.create_task(item.process.wait()),
    )
    state.issued_context = context if sealed else None
    started = StartedContainedProcess(
        item.process,
        item.parent,
        window(),
        7770,
        item.parent.kernel.cgroup_path,
        "observed_path",
        item.owner,
    )
    calls: list[str] = []

    class Stopper:
        async def stop(self, *args: object) -> None:
            calls.append("stop")
            assert not item.owner._closed
            raise stop_failure

    async def finish() -> bool:
        calls.append("drain")
        assert not item.owner._closed
        item.transport.kill()
        await asyncio.gather(state.out, state.err, state.wait)
        return False

    owners: set[asyncio.Future[object]] = set()
    original_close = item.owner.close

    def failed_close() -> bool:
        import os

        real_close, held = os.close, item.owner._root_fd

        def close(fd: int) -> None:
            if fd == held:
                raise OSError("supplied actual FD close failure")
            real_close(fd)

        with monkeypatch.context() as patch:
            patch.setattr(os, "close", close)
            return original_close()

    if close_failure:
        monkeypatch.setattr(item.owner, "close", failed_close)
    try:
        result = await finish_owned_cleanup(
            cast(ContainedOwnedStop, Stopper()),
            started,
            binding(),
            ObservationDeadline(end_us=13_000_000),
            state,
            first,
            finish,
            owners,
            lambda: 12_020_000,
        )
        assert result.first is first and item.owner._closed
        assert result.issued_cleanup == ("deferred" if close_failure else "closed")
        assert result.owner is item.owner and result.process is item.process
        assert result.resources_settled() is not close_failure
        assert calls == (["stop", "drain"] if sealed else ["drain"])
        assert result.unresolved is (sealed or close_failure)
        if sealed:
            assert first.__dict__["_nexus_owned_stop_error"] is stop_failure
    finally:
        item.transport.kill()
        await asyncio.gather(state.out, state.err, state.wait, return_exceptions=True)
        original_close()


async def test_caller_cancellation_retains_cleanup_task_and_original_guard_until_settlement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    from nexus.builder.contained_owned_stop import ContainedOwnedStop
    from nexus.builder.contained_owned_stop_lifecycle import finish_owned_cleanup

    item = await prepared(monkeypatch, cast(Path, tmp_path))
    context = item.owner.seal(await fixed_seal(monkeypatch))
    assert item.process.stdout is not None and item.process.stderr is not None
    state = ProcessSampling(
        asyncio.create_task(item.process.stdout.read()),
        asyncio.create_task(item.process.stderr.read()),
        asyncio.create_task(item.process.wait()),
    )
    state.issued_context = context
    started = StartedContainedProcess(
        item.process,
        item.parent,
        window(),
        7770,
        item.parent.kernel.cgroup_path,
        "observed_path",
        item.owner,
    )
    first = ValueError("original guard denial")
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    class Stopper:
        async def stop(self, *args: object) -> None:
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            assert not item.owner._closed

    async def finish() -> bool:
        item.transport.kill()
        await asyncio.gather(state.out, state.err, state.wait)
        return False

    owners: set[asyncio.Future[object]] = set()
    caller = asyncio.create_task(
        finish_owned_cleanup(
            cast(ContainedOwnedStop, Stopper()),
            started,
            binding(),
            ObservationDeadline(end_us=13_000_000),
            state,
            first,
            finish,
            owners,
            lambda: 12_020_000,
        )
    )
    try:
        await entered.wait()
        caller.cancel("later cancellation")
        with pytest.raises(ValueError) as caught:
            await caller
        assert caught.value is first
        task = first.__dict__["_nexus_owned_cleanup_task"]
        assert task in owners and not task.cancelled() and not task.done()
        assert not item.owner._closed and calls == 1
        release.set()
        result = await task
        assert result.first is first and result.issued_cleanup == "closed"
        assert item.owner._closed and calls == 1
        await asyncio.sleep(0)
        assert not owners
    finally:
        release.set()
        await asyncio.gather(caller, *owners, return_exceptions=True)
        item.transport.kill()
        await asyncio.gather(state.out, state.err, state.wait, return_exceptions=True)
        item.owner.close()


async def test_timely_cancel_can_stop_while_normal_drain_is_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from nexus.builder.contained_owned_stop import ContainedOwnedStop
    from nexus.builder.contained_owned_stop_lifecycle import (
        OwnedCleanupResult,
        finish_owned_cleanup,
    )
    from nexus.tests.unit.test_contained_owned_stop import install, owned

    item, context, started = await owned(monkeypatch, tmp_path)
    assert item.process.stdout is not None and item.process.stderr is not None
    state = ProcessSampling(
        asyncio.create_task(item.process.stdout.read()),
        asyncio.create_task(item.process.stderr.read()),
        asyncio.create_task(item.process.wait()),
    )
    state.issued_context = context
    now = [12_020_000]
    stopper = ContainedOwnedStop(clock=lambda: now[0])
    calls = install(monkeypatch, stopper, context)
    entered, release = asyncio.Event(), asyncio.Event()

    async def drain() -> bool:
        entered.set()
        await release.wait()  # Existing ordinary drain holds an actual pending owner.
        item.transport.kill()
        await asyncio.gather(state.out, state.err, state.wait)
        return False

    owners: set[asyncio.Future[object]] = set()
    caller = asyncio.create_task(
        finish_owned_cleanup(
            stopper,
            started,
            binding(),
            ObservationDeadline(end_us=13_000_000),
            state,
            None,
            drain,
            owners,
            lambda: now[0],
        )
    )
    cleanup: asyncio.Task[object] | None = None
    try:
        await entered.wait()
        caller.cancel("timely cancellation during normal drain")
        with pytest.raises(asyncio.CancelledError) as caught:
            await caller
        cleanup = cast(asyncio.Task[object], caught.value.__dict__["_nexus_owned_cleanup_task"])
        await asyncio.sleep(0)
        before = len(calls)
        assert not cleanup.done() and not item.owner._closed
        now[0] = 13_000_000
        release.set()
        result = await cleanup
        assert isinstance(result, OwnedCleanupResult)
        assert result.first is caught.value and item.owner._closed
        assert before > 0, "Timely cancellation is invisible until blocked drain returns at end"
    finally:
        release.set()
        item.transport.kill()
        await asyncio.gather(
            caller, *owners, state.out, state.err, state.wait, return_exceptions=True
        )
        item.owner.close()
