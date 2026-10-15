"""Actual provider/process composition uses mocked OS children; no native/engine work."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import nexus.builder.contained_process as module
from nexus.builder.contained_contracts import KernelScopeFacts
from nexus.builder.contained_diagnostic_wiring import persist_raw
from nexus.builder.contained_diagnostics import ContainmentDiagnosticStore, DiagnosticIdentity
from nexus.builder.contained_discovery import ContainedDiscovery, decode_discovery
from nexus.builder.contained_evidence_types import ExactContainer, ObservationDeadline
from nexus.builder.contained_process import ContainedProcess
from nexus.builder.contained_process_contracts import PreparedContainedLaunch
from nexus.builder.contained_services import ContainmentServices
from nexus.builder.systemd_scope_provider import SystemdScopeProvider
from nexus.tests.contained_process_fixture import Process, binding, launch, parent
from nexus.tests.unit.test_contained_discovery import body
from nexus.tests.unit.test_contained_process import Watch
from nexus.tests.unit.test_systemd_scope_provider import FakeReader, reports


# Keep the complete fake lifecycle and real durable metadata roundtrip together (>50 lines):
# the original exception, raw capture and private record must describe the same failed call.
async def test_parent_failure_after_seal_is_retained_and_splice_denied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    child = Process(stopped=False)
    reads = 0

    async def kernel() -> KernelScopeFacts:
        nonlocal reads
        reads += 1
        result = parent().kernel
        return result if reads == 1 else result.model_copy(update={"self_cgroup_path": "/foreign"})

    async def spawn(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        return cast(asyncio.subprocess.Process, child)

    class Discovery:
        async def discover(
            self, prepared: PreparedContainedLaunch, pid: int, end: int, **kwargs: object
        ) -> ExactContainer:
            return decode_discovery(body(), prepared, runtime_pid=pid)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(module, "_proc", lambda _: (7770, parent().kernel.cgroup_path))
    provider = SystemdScopeProvider(
        reader=FakeReader(reports() * 2), kernel_reader=kernel, clock_us=lambda: 12_020_000
    )
    process = ContainedProcess(
        provider,
        cast(ContainedDiscovery, Discovery()),
        clock_us=lambda: 12_020_000,
        utc_now=lambda: datetime(2026, 10, 15, tzinfo=UTC) + timedelta(milliseconds=20),
    )
    end = ObservationDeadline(end_us=13_000_000)
    raw = await process.run(
        launch(),
        binding(),
        parent().expectation,
        Watch([]),
        end,
        stdout_limit=1024,
        stderr_limit=1024,
    )
    assert raw.capture.interruption == "ValueError" and raw.infrastructure == "unresolved"
    assert raw.sealed_container is not None and raw.samples == () and child.killed
    record = raw.diagnostic
    assert record is not None and record.parent_attempt == raw.parent_attempt
    failed = raw.parent_attempt
    assert failed is not None and failed.ordinal == 2 and failed.stage == "validate"
    assert failed.kernel is not None and failed.kernel.self_cgroup_path == "/foreign"
    store = ContainmentDiagnosticStore(tmp_path / "diagnostics")
    services = cast(ContainmentServices, SimpleNamespace(diagnostics=store, deadline=end))
    import nexus.builder.contained_diagnostic_wiring as wiring

    monkeypatch.setattr(wiring, "clock_us", lambda: 12_040_000)
    identity = DiagnosticIdentity.model_validate(
        {key: getattr(binding(), key) for key in DiagnosticIdentity.model_fields}
    )
    reference = await persist_raw(raw, identity, services)
    assert await store.load_exact(reference, identity) == record
    spliced = record.model_copy(
        update={"parent_attempt": failed.model_copy(update={"expectation_sha256": "f" * 64})}
    )
    with pytest.raises(ValueError, match="diagnostic"):
        await persist_raw(raw.model_copy(update={"diagnostic": spliced}), identity, services)
