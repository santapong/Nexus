"""Existing owned reads retain controlled failure metadata; no job/engine/DB or liveness change."""

import asyncio
import os
from pathlib import Path

import pytest

from nexus.builder.issued_diagnostics import issued_failure
from nexus.tests.issued_membership_fixture import fixed_seal, prepared


@pytest.mark.parametrize(
    "variation,step",
    [
        ("exited", "runtime_initial"),
        ("collector_reused", "before_membership"),
        ("runtime_reused", "before_membership"),
        ("kernel_path", "kernel_placement"),
        ("root", "root_identity"),
        ("leaf", "held_leaf"),
    ],
)
async def test_exact_failed_owned_predicate_retains_observed_operands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    variation: str,
    step: str,
) -> None:
    item = await prepared(monkeypatch, tmp_path)
    context = item.owner.seal(await fixed_seal(monkeypatch))
    token = object()
    try:
        item.migrate()
        await context.observe(item.parent.expectation, item.kernel, 13_000_000)
        if variation == "exited":
            item.transport.code = 0
        elif variation in ("collector_reused", "runtime_reused"):
            pid = os.getpid() if variation == "collector_reused" else 777
            item.proc[pid] = (9999, item.proc[pid][1])
        elif variation == "kernel_path":
            item.kernel = item.kernel.model_copy(update={"self_cgroup_path": "/foreign"})
        else:
            path = item.root if variation == "root" else item.leaf
            path.rename(path.with_name(path.name + "-retained"))
            path.mkdir()
        with pytest.raises(ValueError) as captured:
            await context.observe(
                item.parent.expectation,
                item.kernel,
                13_000_000,
                call_token=token,
            )
        result = issued_failure(
            captured.value, token, item.parent.expectation, 12_000_000, 13_000_000
        )
        assert result is not None and result.step == step and result.error_type == "ValueError"
        assert len(result.model_dump_json().encode()) <= 4096
        assert (
            issued_failure(
                captured.value, object(), item.parent.expectation, 12_000_000, 13_000_000
            )
            is None
        )
        assert result.operands is not None
        if variation == "exited":
            assert result.operands.runtime_returncode == 0
            assert result.operands.collector_before is None
        if variation == "collector_reused":
            assert result.operands.collector_before is not None
            assert result.operands.collector_before.start_ticks == 9999
    finally:
        item.owner.close()


async def test_actual_proc_oserror_retains_same_exception_without_rereading(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import nexus.builder.contained_issued_context as module

    item = await prepared(monkeypatch, tmp_path)
    context = item.owner.seal(await fixed_seal(monkeypatch))
    item.migrate()
    calls = 0
    failure = PermissionError(13, "nominated proc denial")

    def denied(pid: int) -> tuple[int, str]:
        nonlocal calls
        calls += 1
        raise failure

    monkeypatch.setattr(module, "_proc", denied)
    token = object()
    try:
        with pytest.raises(PermissionError) as captured:
            await context.observe(
                item.parent.expectation,
                item.kernel,
                13_000_000,
                call_token=token,
            )
        assert captured.value is failure and calls == 1
        result = issued_failure(failure, token, item.parent.expectation, 12_000_000, 13_000_000)
        assert result is not None and result.step == "collector_before" and result.errno == 13
        assert result.operands is not None
        assert result.operands.collector_before is None and result.operands.runtime_before is None
    finally:
        item.owner.close()


async def test_exact_provider_call_retains_current_runtime_exit_operands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nexus.builder.contained_parent_diagnostics import failure_parent_attempt
    from nexus.builder.systemd_scope_provider import SystemdScopeProvider
    from nexus.tests.unit.test_systemd_scope_provider import FakeReader, reports

    item = await prepared(monkeypatch, tmp_path)
    context = item.owner.seal(await fixed_seal(monkeypatch))
    item.migrate()
    item.transport.code = 0

    from nexus.builder.contained_contracts import KernelScopeFacts

    async def kernel() -> KernelScopeFacts:
        return item.kernel

    provider = SystemdScopeProvider(
        reader=FakeReader(reports()), kernel_reader=kernel, clock_us=lambda: 12_020_000
    )
    try:
        with pytest.raises(ValueError) as captured:
            await provider.observe_after_owned_spawn(item.parent.expectation, context)
        record = failure_parent_attempt(captured.value, item.parent.expectation)
        assert record is not None and record.issued_failure is not None
        assert (
            record.stage == "issued_membership" and record.issued_failure.step == "runtime_initial"
        )
        operands = record.issued_failure.operands
        assert operands is not None and operands.runtime_returncode_observed
        assert operands.runtime_returncode == 0 and operands.collector_before is None
        assert "issued_failure" in record.model_dump()
    finally:
        item.owner.close()


def test_attachment_rejects_new_exception_stale_clock_scope_and_coercions() -> None:
    from uuid import UUID

    from pydantic import ValidationError

    from nexus.builder.issued_diagnostics import FailureRecorder, IssuedFailure, Operands
    from nexus.tests.contained_process_fixture import parent

    current = parent().expectation
    token, error = object(), ValueError("original")
    recorder = FailureRecorder(current, "a" * 64, 13_000_000)
    recorder.remember("closed", False)
    recorder.attach(error, token, 12_020_000)
    original = issued_failure(error, token, current, 12_000_000, 13_000_000)
    assert original is not None
    copied = ValueError("copied")
    copied.__dict__.update(error.__dict__)
    assert issued_failure(copied, token, current, 12_000_000, 13_000_000) is None
    assert issued_failure(error, token, current, 12_030_000, 13_000_000) is None
    assert (
        issued_failure(
            error,
            token,
            current.model_copy(update={"action_id": UUID(int=9)}),
            12_000_000,
            13_000_000,
        )
        is None
    )
    for update in ({"step": "caller-stage"}, {"truncated": 1}, {"observed_bytes": True}):
        with pytest.raises(ValidationError):
            IssuedFailure.model_validate(original.model_dump() | update)
    with pytest.raises(ValidationError):
        Operands.model_validate({"closed": 1})


def test_oversized_or_invalid_observed_metadata_never_fabricates_replacement_facts() -> None:
    from nexus.builder.issued_diagnostics import FailureRecorder
    from nexus.tests.contained_process_fixture import parent

    token = object()
    recorder = FailureRecorder(parent().expectation, "a" * 64, 13_000_000)
    recorder.remember("collector_before", (1111, "/" + "x" * 3500))
    error = ValueError("original predicate")
    recorder.attach(error, token, 12_020_000)
    result = issued_failure(error, token, parent().expectation, 12_000_000, 13_000_000)
    assert result is not None and result.truncated and result.operands is None
    assert result.observed_bytes is not None and result.observed_bytes > 3000
    assert result.observed_sha256 is not None and len(result.model_dump_json()) < 4096
    recorder.remember("closed", "bad boolean")
    recorder.attach(error, token, 12_020_000)
    result = issued_failure(error, token, parent().expectation, 12_000_000, 13_000_000)
    assert result is not None and result.metadata_unavailable and result.operands is None
    assert result.observed_bytes is None and result.observed_sha256 is None


async def test_cancelled_worker_snapshot_cannot_backfill_late_reads_or_lose_fd_ownership(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import threading

    import nexus.builder.contained_issued_context as module

    item = await prepared(monkeypatch, tmp_path)
    context = item.owner.seal(await fixed_seal(monkeypatch))
    item.migrate()
    entered, release = threading.Event(), threading.Event()

    def finite(pid: int) -> tuple[int, str]:
        entered.set()
        if not release.wait(2):
            raise TimeoutError("nominated finite worker")
        return item.proc[pid]

    monkeypatch.setattr(module, "_proc", finite)
    token = object()
    task = asyncio.create_task(
        context.observe(item.parent.expectation, item.kernel, 13_000_000, call_token=token)
    )
    try:
        async with asyncio.timeout(1):
            while not entered.is_set():
                await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError) as captured:
            await task
        record = issued_failure(
            captured.value, token, item.parent.expectation, 12_000_000, 13_000_000
        )
        assert record is not None and record.step == "collector_before"
        assert record.error_type == "CancelledError" and record.operands is not None
        assert record.operands.collector_before is None
        frozen = record.model_dump_json()
        assert not item.owner.close() and item.owner._pending
        release.set()
        await asyncio.gather(*tuple(item.owner._pending), return_exceptions=True)
        assert record.model_dump_json() == frozen
        assert item.owner.close() and item.owner._root_fd is None and item.owner._leaf_fd is None
    finally:
        release.set()
        await asyncio.gather(*tuple(item.owner._pending), return_exceptions=True)
        item.owner.close()
