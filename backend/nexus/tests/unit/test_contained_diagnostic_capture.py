"""Real discovery/process logic with mocked OS children; no engine or native effect is issued."""

import asyncio
import base64
import hashlib
from typing import cast

import pytest

import nexus.builder.contained_discovery as discovery
import nexus.builder.contained_process as module
from nexus.builder.contained_diagnostics import ContainmentDiagnosticStore, DiscoveryRecorder
from nexus.builder.contained_evidence_types import ObservationDeadline
from nexus.tests.contained_process_fixture import Process, binding, launch, parent
from nexus.tests.unit.test_contained_discovery_transport import pipe
from nexus.tests.unit.test_contained_process import Watch, driver


# One lifecycle keeps the three real mocked inspect attempts and durable record assertions
# together; it slightly exceeds 50 lines without issuing an engine or native action.
async def test_nonzero_discovery_and_completed_body_stay_unproven_with_durable_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    runtime = Process(stopped=False)
    runtime.stdout = pipe(b"ORIGINAL COMMAND BODY NOT A DIAGNOSTIC PREFIX")
    calls = 0

    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        nonlocal calls
        if args[3] == "run":
            return cast(asyncio.subprocess.Process, runtime)
        assert args[3] == "inspect"
        calls += 1
        child = Process()
        child.returncode = 125
        child.stdout = pipe(b"")
        child.stderr = pipe(b"fixed local inspect not available")
        if calls == 3:
            runtime.returncode = 0
            runtime.done.set()
        return cast(asyncio.subprocess.Process, child)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(discovery, "clock_us", lambda: 12_020_000)
    monkeypatch.setattr(module, "_proc", lambda _: (7770, parent().kernel.cgroup_path))
    result = await driver([]).run(
        launch(),
        binding(),
        parent().expectation,
        Watch([]),
        ObservationDeadline(end_us=13_000_000),
        stdout_limit=4096,
        stderr_limit=4096,
    )
    assert result.infrastructure == "unproven" and result.capture.interruption is None
    assert result.samples == () and result.sealed_container is None
    diagnostic = result.diagnostic
    assert diagnostic is not None
    assert diagnostic.discovery.total == 3 and diagnostic.discovery.omitted == 1
    first, last = diagnostic.discovery.first, diagnostic.discovery.last
    assert first is not None and last is not None and first.index == 1 and last.index == 3
    assert first.exit_code == 125 and last.error_type == "DiscoveryUnavailableError"
    assert base64.b64decode(last.stderr.prefix_base64) == b"fixed local inspect not available"
    assert diagnostic.stdout.observed_sha256 == hashlib.sha256(result.capture.stdout).hexdigest()
    assert b"ORIGINAL COMMAND BODY" not in diagnostic.model_dump_json().encode()
    store = ContainmentDiagnosticStore(tmp_path / "diagnostics")
    ref = await store.save_once(diagnostic)
    assert await store.load_exact(ref, diagnostic.identity) == diagnostic


async def test_positive_pid_startup_decoder_outcomes_are_unchanged_and_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from nexus.tests.unit.test_contained_discovery import body
    from nexus.tests.unit.test_contained_discovery_transport import install

    value = json.loads(body()) | {"running": False, "payload_pid": 0, "conmon_pid": 0}
    child = Process()
    child.stdout = pipe(json.dumps(value).encode())
    install(monkeypatch, child)
    recorder = DiscoveryRecorder()
    with pytest.raises(ValueError):
        await discovery.ContainedDiscovery().discover(launch(), 777, 13_000_000, recorder=recorder)
    trace = recorder.snapshot()
    assert trace.total == 1 and trace.first is not None
    assert trace.first.error_type == "ValidationError" and trace.first.exit_code == 0
    assert trace.first.stdout.complete and trace.first.reaped


@pytest.mark.parametrize("field,limit", [("stdout", 65536), ("stderr", 4096)])
async def test_overflow_counts_and_hash_describe_observed_prefix_only(
    monkeypatch: pytest.MonkeyPatch, field: str, limit: int
) -> None:
    from nexus.tests.unit.test_contained_discovery_transport import install

    child = Process(stopped=False)
    setattr(child, field, pipe(b"x" * (limit + 1)))
    install(monkeypatch, child)
    recorder = DiscoveryRecorder()
    with pytest.raises(ValueError):
        await discovery.ContainedDiscovery().discover(launch(), 777, 13_000_000, recorder=recorder)
    row = recorder.snapshot().first
    assert row is not None
    stream = getattr(row, field)
    assert stream.observed_bytes == limit + 1 and stream.overflow and not stream.complete
    assert stream.observed_sha256 == hashlib.sha256(b"x" * (limit + 1)).hexdigest()
    assert len(base64.b64decode(stream.prefix_base64)) == 4096
