"""Mocked process lifecycle covers failed discovery, capture, cleanup and shared deadlines."""

import asyncio
from collections.abc import Callable
from typing import cast

import pytest

import nexus.builder.contained_process as module
from nexus.builder.contained_contracts import ParentObservation
from nexus.builder.contained_diagnostics import DiscoveryRecorder
from nexus.builder.contained_discovery import ContainedDiscovery
from nexus.builder.contained_evidence_types import ExactContainer, ObservationDeadline
from nexus.builder.contained_observer import ContainmentObserver
from nexus.builder.contained_observer_io import OwnedObservationIO
from nexus.builder.contained_process import ContainedProcess
from nexus.builder.contained_process_contracts import ContainedRunCapture, PreparedContainedLaunch
from nexus.tests.contained_process_fixture import Process, binding, launch, parent
from nexus.tests.unit.test_contained_process import Watch, driver


def install(monkeypatch: pytest.MonkeyPatch, child: Process, path: str | None = None) -> None:
    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        return cast(asyncio.subprocess.Process, child)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(module, "_proc", lambda _: (7770, path or parent().kernel.cgroup_path))


async def run(
    value: ContainedProcess, watch: Watch | None = None, limit: int = 1024
) -> ContainedRunCapture:
    return await value.run(
        launch(),
        binding(),
        parent().expectation,
        watch or Watch([]),
        ObservationDeadline(end_us=13_000_000),
        stdout_limit=limit,
        stderr_limit=1024,
    )


@pytest.mark.asyncio
async def test_short_process_without_samples_is_unproven_and_retains_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Process()
    install(monkeypatch, child)
    result = await run(driver([]))
    assert result.infrastructure == "unproven" and result.samples == ()
    assert result.runtime.pid == 777 and result.runtime.start_ticks == 7770
    assert result.runtime.parent_membership == "observed_path" and result.runtime.reap == "waited"
    assert result.capture.stdout == b"short original output" and not child.killed


@pytest.mark.asyncio
async def test_runtime_outside_parent_is_issued_unknown_with_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Process()
    install(monkeypatch, child, "/foreign/sibling")
    result = await run(driver([]))
    assert (
        result.infrastructure == "unresolved" and result.runtime.parent_membership == "foreign_path"
    )
    assert result.runtime.cgroup_path == "/foreign/sibling" and not result.samples


@pytest.mark.asyncio
async def test_output_overflow_retains_capped_original_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Process()
    install(monkeypatch, child)
    result = await run(driver([]), limit=5)
    assert result.infrastructure == "unresolved" and result.capture.stdout == b"short"
    assert result.runtime.reap == "waited"


@pytest.mark.asyncio
async def test_stalled_monitor_watch_cannot_outlive_shared_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Process(stopped=False)
    install(monkeypatch, child)

    class Blocked(Watch):
        async def check(self) -> None:
            await asyncio.Event().wait()

    value = driver([], clock=lambda: 12_850_000)
    result = await run(value, Blocked([]))
    assert result.infrastructure == "unresolved" and result.capture.interruption == "TimeoutError"
    assert child.killed and result.runtime.reap == "waited"


@pytest.mark.asyncio
async def test_cleanup_pid_reader_bound_and_unknown_without_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Process(stopped=False)
    install(monkeypatch, child)
    entered = asyncio.Event()
    reads = 0

    async def proc(call: Callable[[int], tuple[int, str]], pid: int) -> tuple[int, str]:
        nonlocal reads
        reads += 1
        if reads == 1:
            return (7770, parent().kernel.cgroup_path)
        entered.set()
        await asyncio.Event().wait()
        return (7770, parent().kernel.cgroup_path)

    monkeypatch.setattr(asyncio, "to_thread", proc)

    class Denied(Watch):
        async def check(self) -> None:
            raise ValueError("source revoked")

    result = await run(driver([], clock=lambda: 12_850_000), Denied([]))
    assert entered.is_set() and not child.killed
    assert result.infrastructure == "unresolved" and result.runtime.reap == "unresolved"


@pytest.mark.asyncio
async def test_reused_pid_start_never_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    child = Process(stopped=False)
    install(monkeypatch, child)
    reads = iter(((7770, parent().kernel.cgroup_path), (9999, parent().kernel.cgroup_path)))
    monkeypatch.setattr(module, "_proc", lambda _: next(reads))

    class Denied(Watch):
        async def check(self) -> None:
            raise ValueError("source revoked")

    result = await run(driver([], clock=lambda: 12_850_000), Denied([]))
    assert not child.killed and result.runtime.start_ticks == 7770
    assert result.runtime.reap == "unresolved" and result.infrastructure == "unresolved"


@pytest.mark.asyncio
async def test_cancel_monitor_reaps_original_child_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Process(stopped=False)
    install(monkeypatch, child)
    entered = asyncio.Event()

    class Blocked(Watch):
        async def check(self) -> None:
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(run(driver([]), Blocked([])))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert child.killed and child.wait_count >= 1


@pytest.mark.asyncio
async def test_each_job_uses_distinct_observer(monkeypatch: pytest.MonkeyPatch) -> None:
    child = Process()
    install(monkeypatch, child)
    seen: list[object] = []
    real = ContainmentObserver

    def observer(io: OwnedObservationIO) -> ContainmentObserver:
        result = real(io)
        seen.append(result)
        return result

    monkeypatch.setattr(module, "ContainmentObserver", observer)
    value = driver([])
    await run(value)
    await run(value)
    assert len(seen) == 2 and seen[0] is not seen[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_sample", [False, True])
# The cohesive fake discovery/IO lifecycle exceeds 50 lines to verify both actual observer
# outcomes and their diagnostic summaries under the same shared end.
async def test_monitor_composes_real_observer_with_one_shared_end(
    monkeypatch: pytest.MonkeyPatch,
    failed_sample: bool,
) -> None:
    from nexus.builder.contained_discovery import decode_discovery
    from nexus.builder.contained_evidence_types import ObservedSample, ProcessIdentity
    from nexus.tests.contained_observer_fixture import process as observed_process
    from nexus.tests.unit.test_contained_discovery import body
    from nexus.tests.unit.test_contained_evidence_types import sample

    child = Process(stopped=False)
    install(monkeypatch, child)
    exact = decode_discovery(body(), launch(), runtime_pid=777)
    calls: list[int] = []

    class Discovery:
        async def discover(
            self,
            prepared: PreparedContainedLaunch,
            runtime_pid: int,
            deadline_us: int,
            *,
            recorder: DiscoveryRecorder | None = None,
        ) -> ExactContainer:
            assert runtime_pid == 777 and prepared == launch()
            calls.append(deadline_us)
            return exact

    class IO:
        async def observe(
            self,
            current: ParentObservation,
            container: ExactContainer,
            deadline: ObservationDeadline,
            previous: tuple[ProcessIdentity, ...],
        ) -> ObservedSample:
            assert previous == () and container == exact
            calls.append(deadline.end_us)
            if failed_sample:
                raise ValueError("Generated first sample missing kernel witness")
            row = sample().model_dump() | {
                "container": exact.model_dump(),
                "processes": (
                    observed_process(101, "payload").model_dump(),
                    observed_process(102, "conmon").model_dump(),
                    observed_process(777, "runtime").model_dump(),
                ),
            }
            child.returncode = 0
            child.done.set()
            return ObservedSample.model_validate(row)

    real = ContainmentObserver

    def observer(io: OwnedObservationIO) -> ContainmentObserver:
        return real(IO(), clock_us=lambda: 12_020_000)

    monkeypatch.setattr(module, "ContainmentObserver", observer)
    value = driver([])
    value.discovery = cast(ContainedDiscovery, Discovery())
    result = await run(value)
    assert calls == [13_000_000, 13_000_000]
    assert result.infrastructure == ("unresolved" if failed_sample else "known")
    assert len(result.samples) == 1
    assert result.runtime.reap == "waited" and result.sealed_container == exact
    from nexus.builder.contained_process_contracts import sample_trace

    assert result.diagnostic is not None
    assert result.diagnostic.samples == sample_trace(result.samples)
    assert result.diagnostic.samples.first is not None
    assert result.diagnostic.samples.first.status == result.samples[0].status
    assert result.diagnostic.samples.first.diagnostics == result.samples[0].diagnostics


@pytest.mark.asyncio
async def test_capture_validation_cpu_crossing_end_cannot_return_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Process()
    install(monkeypatch, child)
    ticks = [12_020_000]

    def slow_validation(**fields: object) -> ContainedRunCapture:
        result = ContainedRunCapture.model_validate(fields)
        ticks[0] = 13_000_001
        return result

    import nexus.builder.contained_process_contracts as contracts

    monkeypatch.setattr(contracts, "ContainedRunCapture", slow_validation)
    result = await run(driver([], clock=lambda: ticks[0]))
    assert result.infrastructure == "unresolved" and result.runtime.reap == "waited"
    assert result.limitations == ("shared_deadline_expired",)
