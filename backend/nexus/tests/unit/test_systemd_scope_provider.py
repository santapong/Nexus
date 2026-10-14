"""Typed fixed queries and provider ordering are tested with actual parsers, no scope mutation."""

import asyncio
import json
from collections.abc import Sequence
from typing import cast

import pytest

from nexus.builder.contained_contracts import KernelScopeFacts
from nexus.builder.contained_query import BusctlReader, clock_us
from nexus.builder.systemd_scope_provider import (
    SystemdScopeProvider,
    decode_records,
    object_path,
    query_arguments,
)
from nexus.tests.unit.test_contained_scope import (
    GROUP,
    INVOCATION,
    UNIT,
    expectation,
    kernel_facts,
)


def reports() -> list[bytes]:
    """Literal typed busctl reply shapes confirmed on systemd261.2."""
    batches: list[list[tuple[str, object]]] = [
        [("o", [object_path(UNIT)])],
        [
            ("s", UNIT),
            ("s", "loaded"),
            ("s", "active"),
            ("ay", list(INVOCATION.bytes)),
            ("t", 10_000_000),
        ],
        [
            ("s", GROUP),
            ("t", 1_200_000_000),
            ("t", 0),
            ("b", True),
            ("t", 4_294_967_296),
            ("t", 2_000_000),
            ("t", 100_000),
            ("t", 256),
            ("s", "control-group"),
            ("b", True),
            ("t", 1_000_000),
        ],
    ]
    return [
        b"\n".join(json.dumps({"type": kind, "data": value}).encode() for kind, value in batch)
        + b"\n"
        for batch in batches
    ]


class FakeReader:
    """Only the transport boundary is faked; parser and admission are real."""

    def __init__(self, bodies: Sequence[bytes], delay: float = 0) -> None:
        self.bodies = list(bodies)
        self.delay = delay
        self.calls: list[tuple[str, ...]] = []

    async def query(self, argv: tuple[str, ...], deadline_us: int) -> bytes:
        assert deadline_us > 0
        self.calls.append(argv)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.bodies.pop(0)


async def read_kernel() -> KernelScopeFacts:
    """New scope observations must call the current kernel reader again."""
    return kernel_facts()


@pytest.mark.asyncio
async def test_three_fixed_read_only_queries_accept_current_synthetic_parent() -> None:
    reader = FakeReader(reports())
    clock = iter((11_000_000, 12_000_000))
    provider = SystemdScopeProvider(
        reader=reader, kernel_reader=read_kernel, clock_us=lambda: next(clock)
    )
    row = await provider.observe(expectation())
    assert row.remaining_us == 1_198_000_000
    assert reader.calls == list(query_arguments(UNIT))
    assert all(argv[0] == "/usr/bin/busctl" and "--user" in argv for argv in reader.calls)


@pytest.mark.parametrize(
    "body",
    [
        b'{"type":"t","type":"s","data":1}',
        b'{"type":"t","data":true}',
        b'{"type":"t","data":"1"}',
        b'{"type":"t","data":null}',
        b'{"type":"t","data":18446744073709551615}',
        b'{"type":"t","data":Infinity}',
        b'{"type":"t","data":1,"extra":0}',
        b'{"type":"t","data":1}\n{}',
        b"",
        b"x" * 16385,
    ],
)
def test_raw_reply_duplicate_coercion_unlimited_overflow_and_count_denies(body: bytes) -> None:
    with pytest.raises(ValueError):
        decode_records(body, ("t",))


@pytest.mark.asyncio
async def test_object_path_splice_denies_before_property_or_kernel_reads() -> None:
    raw = reports()
    raw[0] = b'{"type":"o","data":["/org/freedesktop/systemd1/unit/foreign"]}'
    reader = FakeReader(raw)
    provider = SystemdScopeProvider(
        reader=reader, kernel_reader=read_kernel, clock_us=lambda: 11_000_000
    )
    with pytest.raises(ValueError):
        await provider.observe(expectation())
    assert len(reader.calls) == 1


@pytest.mark.asyncio
async def test_total_provider_deadline_denies_early_good_snapshot() -> None:
    reader = FakeReader(reports())
    clock = iter((11_000_000, 14_000_001))
    provider = SystemdScopeProvider(
        reader=reader, kernel_reader=read_kernel, clock_us=lambda: next(clock)
    )
    with pytest.raises(ValueError):
        await provider.observe(expectation())


@pytest.mark.asyncio
async def test_current_provider_never_reuses_previous_unit_or_kernel_facts() -> None:
    good = reports()
    changed = reports()
    changed[1] = changed[1].replace(b'"active"', b'"inactive"')
    reader = FakeReader(good + changed)
    clock = iter((11_000_000, 12_000_000, 13_000_000, 14_000_000))
    provider = SystemdScopeProvider(
        reader=reader, kernel_reader=read_kernel, clock_us=lambda: next(clock)
    )
    await provider.observe(expectation())
    with pytest.raises(ValueError):
        await provider.observe(expectation())
    assert len(reader.calls) == 6


@pytest.mark.asyncio
async def test_total_timeout_bounds_all_three_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = FakeReader(reports(), delay=0.03)
    real_timeout = asyncio.timeout
    monkeypatch.setattr(
        "nexus.builder.systemd_scope_provider.asyncio.timeout", lambda _: real_timeout(0.05)
    )
    provider = SystemdScopeProvider(reader=reader, kernel_reader=read_kernel)
    with pytest.raises(TimeoutError):
        await provider.observe(expectation())
    assert len(reader.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "argv",
    [
        ("/bin/sh", "-c", "true"),
        (
            *query_arguments(UNIT)[0][:6],
            "set-property",
            "org.freedesktop.systemd1",
            "/",
            "x",
            "y",
            "s",
            "z",
        ),
        (*query_arguments(UNIT)[0][:-1], "--help"),
        (*query_arguments(UNIT)[1][:-1], "Unknown"),
    ],
)
async def test_query_transport_rejects_mutation_unknown_or_injected_argv_before_spawn(
    argv: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def forbidden(*args: object, **kwargs: object) -> object:
        pytest.fail("Forbidden query reached subprocess spawn")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    with pytest.raises(ValueError):
        await BusctlReader().query(argv, clock_us() + 3_000_000)


class QueryProcess:
    """Owned query child with real streams and wait/kill observations, no OS process."""

    def __init__(self, body: bytes, *, exit_code: int | None = 0) -> None:
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(body)
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.returncode = exit_code
        self.killed = False
        self.wait_count = 0
        self.done = asyncio.Event()
        if exit_code is not None:
            self.done.set()

    async def wait(self) -> int:
        self.wait_count += 1
        await self.done.wait()
        assert self.returncode is not None
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        self.done.set()


def install_query_process(
    monkeypatch: pytest.MonkeyPatch, process: QueryProcess
) -> list[tuple[str, ...]]:
    """Fake only OS spawn; real transport streams, timeout and exact child cleanup execute."""
    calls: list[tuple[str, ...]] = []

    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        calls.append(args)
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL
        assert kwargs["env"] is not None
        return cast(asyncio.subprocess.Process, process)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return calls


@pytest.mark.asyncio
async def test_actual_query_capture_returns_bytes_and_reaps_exact_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = QueryProcess(reports()[0])
    calls = install_query_process(monkeypatch, process)
    assert (
        await BusctlReader().query(query_arguments(UNIT)[0], clock_us() + 3_000_000) == reports()[0]
    )
    assert calls == [query_arguments(UNIT)[0]]
    assert process.wait_count == 2
    assert not process.killed


@pytest.mark.asyncio
async def test_query_stdout_overflow_kills_and_waits_exact_owned_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = QueryProcess(b"x" * 16385, exit_code=None)
    install_query_process(monkeypatch, process)
    with pytest.raises(ValueError):
        await BusctlReader().query(query_arguments(UNIT)[0], clock_us() + 3_000_000)
    assert process.killed and process.wait_count == 2


@pytest.mark.asyncio
async def test_query_stderr_overflow_cannot_be_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    process = QueryProcess(b"", exit_code=None)
    process.stderr = asyncio.StreamReader()
    process.stderr.feed_data(b"x" * 4097)
    process.stderr.feed_eof()
    install_query_process(monkeypatch, process)
    with pytest.raises(ValueError):
        await BusctlReader().query(query_arguments(UNIT)[0], clock_us() + 3_000_000)
    assert process.killed and process.wait_count == 2


@pytest.mark.asyncio
async def test_query_nonzero_exit_cannot_license_partial_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = QueryProcess(reports()[0], exit_code=1)
    install_query_process(monkeypatch, process)
    with pytest.raises(ValueError, match="unavailable"):
        await BusctlReader().query(query_arguments(UNIT)[0], clock_us() + 3_000_000)
    assert process.wait_count == 2


@pytest.mark.asyncio
async def test_unconfirmed_child_reap_cannot_return_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = QueryProcess(b"", exit_code=None)
    install_query_process(monkeypatch, process)

    async def unconfirmed() -> int:
        process.wait_count += 1
        await asyncio.sleep(1)
        return -9

    monkeypatch.setattr(process, "wait", unconfirmed)
    with pytest.raises(TimeoutError):
        await BusctlReader().query(query_arguments(UNIT)[0], clock_us() + 120_000)
    assert process.killed and process.wait_count == 2


@pytest.mark.asyncio
async def test_query_timeout_kills_and_waits_within_reserved_cleanup_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = QueryProcess(b"", exit_code=None)
    install_query_process(monkeypatch, process)
    with pytest.raises(TimeoutError):
        await BusctlReader().query(query_arguments(UNIT)[0], clock_us() + 120_000)
    assert process.killed and process.wait_count == 2


@pytest.mark.asyncio
async def test_query_cancellation_reaps_exact_child_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = QueryProcess(b"", exit_code=None)
    calls = install_query_process(monkeypatch, process)
    task = asyncio.create_task(
        BusctlReader().query(query_arguments(UNIT)[0], clock_us() + 3_000_000)
    )
    while not process.wait_count:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == [query_arguments(UNIT)[0]]
    assert process.killed and process.wait_count == 2
