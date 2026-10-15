"""Nominated fixed-query/kernel failures retain metadata; no scope or engine is executed."""

import base64
import hashlib
import json
from pathlib import Path

import pytest

from nexus.builder.contained_contracts import KernelScopeFacts
from nexus.builder.contained_parent_diagnostics import (
    ParentAttempt,
    ParentQuery,
    ParentRecorder,
    failure_parent_attempt,
)
from nexus.builder.contained_scope import validate_current_scope
from nexus.builder.systemd_scope_provider import SystemdScopeProvider
from nexus.tests.unit.test_contained_scope import expectation, kernel_facts
from nexus.tests.unit.test_systemd_scope_provider import FakeReader, read_kernel, reports


async def test_valid_metadata_describes_same_parent_without_authority() -> None:
    provider = SystemdScopeProvider(
        reader=FakeReader(reports()), kernel_reader=read_kernel, clock_us=lambda: 11_000_000
    )
    value = await provider.observe(expectation())
    record = provider.last_diagnostic
    assert record is not None and record.stage == "complete" and record.code == "none"
    assert record.unit == value.unit and record.kernel == value.kernel
    assert len(record.queries) == 5 and all(row.complete for row in record.queries)
    assert (
        record.expectation_sha256
        == hashlib.sha256(expectation().model_dump_json().encode()).hexdigest()
    )
    assert "permit" not in record.model_dump() and "body" not in record.model_dump()


@pytest.mark.parametrize(
    "field,value", [("self_cgroup_path", "/foreign"), ("cpu_quota_us", 100001)]
)
async def test_actual_nominated_kernel_mismatch_can_be_replayed_without_acceptance(
    field: str, value: object
) -> None:
    async def changed() -> KernelScopeFacts:
        return kernel_facts().model_copy(update={field: value})

    provider = SystemdScopeProvider(
        reader=FakeReader(reports()), kernel_reader=changed, clock_us=lambda: 11_000_000
    )
    with pytest.raises(ValueError, match="kernel scope"):
        await provider.observe(expectation())
    record = provider.last_diagnostic
    assert record is not None and record.stage == "validate" and record.code == "failed_at_stage"
    assert record.unit is not None and record.kernel is not None
    assert getattr(record.kernel, field) == value and record.error_type == "ValueError"
    with pytest.raises(ValueError, match="kernel scope"):
        validate_current_scope(
            expectation(), record.unit, record.kernel, record.started_us, record.finished_us
        )


async def test_previous_success_cannot_fill_early_next_failure() -> None:
    bodies = [*reports(), b'{"type":"u","data":false}']
    provider = SystemdScopeProvider(
        reader=FakeReader(bodies), kernel_reader=read_kernel, clock_us=lambda: 11_000_000
    )
    await provider.observe(expectation())
    with pytest.raises(ValueError):
        await provider.observe(expectation())
    record = provider.last_diagnostic
    assert record is not None and record.ordinal == 2 and record.stage == "manager_uid"
    assert record.unit is None and record.kernel is None and len(record.queries) == 1


async def test_malformed_reply_retains_observed_prefix_before_parse_failure() -> None:
    bodies = reports()
    bodies[3] = b"not typed JSON " * 100
    provider = SystemdScopeProvider(
        reader=FakeReader(bodies), kernel_reader=read_kernel, clock_us=lambda: 11_000_000
    )
    with pytest.raises(ValueError):
        await provider.observe(expectation())
    record = provider.last_diagnostic
    assert record is not None and record.stage == "unit" and record.unit is None
    query = record.queries[-1]
    assert query.observed_bytes == len(bodies[3]) and query.complete
    assert query.observed_sha256 == hashlib.sha256(bodies[3]).hexdigest()
    assert base64.b64decode(query.prefix_base64 or "") == bodies[3][:512]


async def test_kernel_exception_records_only_trustworthy_boundary() -> None:
    async def denied() -> KernelScopeFacts:
        raise ValueError("Scope kernel file exceeds the fixed byte cap")

    provider = SystemdScopeProvider(
        reader=FakeReader(reports()), kernel_reader=denied, clock_us=lambda: 11_000_000
    )
    with pytest.raises(ValueError):
        await provider.observe(expectation())
    record = provider.last_diagnostic
    assert record is not None and record.stage == "kernel" and record.kernel is None
    assert record.unit is not None and record.code == "failed_at_stage"
    assert "Scope kernel file" not in record.model_dump_json()


async def test_metadata_cpu_crossing_original_io_end_never_returns_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = [11_000_000]
    original = ParentRecorder.finish

    def costly(
        self: ParentRecorder, failure: BaseException | None, finished_us: int
    ) -> ParentAttempt:
        result = original(self, failure, finished_us)
        ticks[0] = 14_000_001
        return result

    monkeypatch.setattr(ParentRecorder, "finish", costly)
    provider = SystemdScopeProvider(
        reader=FakeReader(reports()), kernel_reader=read_kernel, clock_us=lambda: ticks[0]
    )
    with pytest.raises(ValueError, match="deadline"):
        await provider.observe(expectation())
    assert provider.last_diagnostic is not None
    assert provider.last_diagnostic.code == "deadline"


async def test_exception_keeps_its_own_call_after_later_success() -> None:
    provider = SystemdScopeProvider(
        reader=FakeReader([b"bad", *reports()]),
        kernel_reader=read_kernel,
        clock_us=lambda: 11_000_000,
    )
    with pytest.raises(ValueError) as caught:
        await provider.observe(expectation())
    await provider.observe(expectation())
    record = failure_parent_attempt(caught.value, expectation())
    assert record is not None and record.ordinal == 1
    assert provider.last_diagnostic is not None and provider.last_diagnostic.ordinal == 2
    copied = record.model_copy(update={"expectation_sha256": "f" * 64})
    caught.value.__dict__["nexus_parent_attempt"] = copied
    with pytest.raises(ValueError, match="scope"):
        failure_parent_attempt(caught.value, expectation())


async def test_query_transport_error_never_claims_unreturned_bytes() -> None:
    class Denied(FakeReader):
        async def query(self, argv: tuple[str, ...], deadline_us: int) -> bytes:
            raise OSError("Nominated local transport failure; not a retained error string")

    provider = SystemdScopeProvider(
        reader=Denied([]), kernel_reader=read_kernel, clock_us=lambda: 11_000_000
    )
    with pytest.raises(OSError):
        await provider.observe(expectation())
    assert provider.last_diagnostic is not None
    query = provider.last_diagnostic.queries[0]
    assert query.observed_bytes is None and query.observed_sha256 is None
    assert query.prefix_base64 is None
    assert not query.complete and not query.overflow and query.error_type == "OSError"


def test_oversized_return_is_explicit_observed_prefix_and_hash_only() -> None:
    recorder = ParentRecorder(1, expectation(), 11_000_000)
    recorder.begin_query(0, ("fixed-metadata-descriptor",))
    recorder.reply(b"x" * 20000)
    query = recorder.finish(ValueError("nominated"), 11_000_000).queries[0]
    assert query.observed_bytes == 16385 and query.overflow and not query.complete
    assert query.observed_sha256 == hashlib.sha256(b"x" * 16385).hexdigest()
    assert base64.b64decode(query.prefix_base64 or "") == b"x" * 512


@pytest.mark.parametrize(
    "change",
    [
        {"prefix_base64": "eA=="},
        {"observed_bytes": 1},
        {"complete": True},
        {"overflow": True},
        {"index": True},
        {"index": 5},
        {"permit": True},
    ],
)
def test_parent_query_unknown_or_bad_shape_cannot_be_filled(change: dict[str, object]) -> None:
    raw = {
        "index": 0,
        "argv_sha256": "a" * 64,
        "observed_bytes": None,
        "observed_sha256": None,
        "prefix_base64": None,
        "complete": False,
        "overflow": False,
    }
    with pytest.raises(ValueError):
        ParentQuery.model_validate(raw | change)


async def test_large_invalid_facts_remain_explicit_digests_within_private_record_cap(
    tmp_path: Path,
) -> None:
    from nexus.builder.contained_diagnostics import ContainmentDiagnosticStore
    from nexus.tests.unit.test_contained_diagnostics import diagnostic
    from nexus.tests.unit.test_contained_scope import unit_facts

    assert isinstance(tmp_path, Path)
    recorder = ParentRecorder(1, expectation(), 11_000_000)
    recorder.stage = "validate"
    unit = unit_facts().model_copy(update={"cgroup_path": "/" + "u" * 17000})
    kernel = kernel_facts().model_copy(update={"self_cgroup_path": "/" + "k" * 9000})
    recorder.unit, recorder.kernel = unit, kernel
    record = recorder.finish(ValueError("nominated oversized invalid facts"), 11_000_000)
    assert record.facts_truncated and record.unit is None and record.kernel is None
    assert record.unit_observed is not None and record.kernel_observed is not None
    for observed, fact in ((record.unit_observed, unit), (record.kernel_observed, kernel)):
        fields = fact.model_dump(mode="json")
        if isinstance(fact, KernelScopeFacts):
            fields["controllers"] = sorted(fact.controllers)
        raw = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        assert (
            observed.byte_length == len(raw) and observed.sha256 == hashlib.sha256(raw).hexdigest()
        )
        assert observed.encoding == "canonical-parsed-parent-facts.v1"
    value = diagnostic().model_copy(update={"parent_attempt": record})
    assert len(value.model_dump_json().encode()) < 65536
    assert b"u" * 512 not in value.model_dump_json().encode()
    store = ContainmentDiagnosticStore(tmp_path / "diagnostics")
    ref = await store.save_once(value)
    assert await store.load_exact(ref, value.identity) == value
    with pytest.raises(ValueError):
        ParentAttempt.model_validate(record.model_dump() | {"facts_truncated": 1})


def test_absent_parent_metadata_keeps_existing_diagnostic_wire() -> None:
    from nexus.tests.unit.test_contained_diagnostic_wiring import raw_capture
    from nexus.tests.unit.test_contained_diagnostics import diagnostic

    assert "parent_attempt" not in diagnostic().model_dump()
    assert "parent_attempt" not in raw_capture().model_dump()
