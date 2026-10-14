"""Private diagnostic records are metadata, not containment references or native authority."""

import hashlib
from pathlib import Path

import pytest

from nexus.builder.contained_diagnostics import (
    ContainmentDiagnosticStore,
    DiagnosticIdentity,
    DiscoveryTrace,
    FinalizationDiagnostic,
    OutputDigest,
    ProcessDiagnostic,
    RuntimeDiagnostic,
    SampleTrace,
)
from nexus.tests.contained_process_fixture import binding


def diagnostic() -> ProcessDiagnostic:
    value = binding()
    identity = DiagnosticIdentity(
        company_id=value.company_id,
        action_id=value.action_id,
        task_id=value.task_id,
        trace_id=value.trace_id,
        run_id=value.run_id,
        original_intent_fence=value.original_intent_fence,
        spec_sha256=value.spec_sha256,
        proposal_sha256=value.proposal_sha256,
        execution_method_sha256=value.execution_method_sha256,
    )
    empty = OutputDigest(observed_bytes=0, observed_sha256=hashlib.sha256(b"").hexdigest())
    return ProcessDiagnostic(
        identity=identity,
        parent_sha256="a" * 64,
        deadline_end_us=13_000_000,
        infrastructure="unproven",
        runtime=RuntimeDiagnostic(
            pid=777,
            start_ticks=7770,
            cgroup_path="/owned",
            parent_membership="observed_path",
            reap="waited",
        ),
        sealed_container=None,
        stdout=empty,
        stderr=empty,
        exit_code=0,
        interruption=None,
        phase="complete",
        error_type="none",
        errno=None,
        discovery=DiscoveryTrace(total=0, first=None, last=None, omitted=0),
        samples=SampleTrace(
            total=0,
            status_counts=(),
            diagnostic_counts=(),
            chain_sha256=hashlib.sha256(b"").hexdigest(),
            first=None,
            last=None,
            omitted=0,
        ),
    )


async def test_private_write_once_raw_and_final_are_distinct_non_authority(tmp_path: Path) -> None:
    store = ContainmentDiagnosticStore(tmp_path / "diagnostics")
    value = diagnostic()
    first = await store.save_once(value)
    assert await store.load_exact(first, value.identity) == value
    assert await store.save_once(value) == first
    assert first.schema_version == "nexus.builder.diagnostic-ref.v1"
    final = FinalizationDiagnostic(
        identity=value.identity,
        status="unproven",
        diagnostics=("no_samples",),
        sample_count=0,
        sample_chain_sha256=value.samples.chain_sha256,
    )
    second = await store.save_once(final)
    assert second.phase == "final" and second != first
    assert "containment" not in value.model_dump() and "body" not in value.model_dump()


@pytest.mark.parametrize("field", ["body", "stdout_body", "commands", "permit", "terminal_receipt"])
def test_body_and_authority_fields_are_not_diagnostic_contract(field: str) -> None:
    with pytest.raises(ValueError):
        ProcessDiagnostic.model_validate(diagnostic().model_dump() | {field: "caller-pass"})


async def test_conflicting_original_record_is_preserved(tmp_path: Path) -> None:
    store = ContainmentDiagnosticStore(tmp_path / "diagnostics")
    value = diagnostic()
    reference = await store.save_once(value)
    changed = value.model_copy(update={"infrastructure": "unresolved"})
    with pytest.raises(ValueError):
        await store.save_once(changed)
    assert await store.load_exact(reference, value.identity) == value


async def test_pending_symlink_and_root_replacement_never_replace_history(tmp_path: Path) -> None:
    import os

    value = diagnostic()
    store = ContainmentDiagnosticStore(tmp_path / "pending")
    pending = store.root / (store.filename(value.identity, "raw") + ".pending")
    pending.write_bytes(b"first uncertain partial")
    pending.chmod(0o600)
    with pytest.raises(FileExistsError):
        await store.save_once(value)
    assert pending.read_bytes() == b"first uncertain partial"
    linked = ContainmentDiagnosticStore(tmp_path / "linked")
    target = tmp_path / "target"
    target.write_bytes(b"not diagnostic")
    target.chmod(0o600)
    (linked.root / linked.filename(value.identity, "raw")).symlink_to(target)
    with pytest.raises(OSError):
        await linked.save_once(value)
    assert target.read_bytes() == b"not diagnostic"
    original = ContainmentDiagnosticStore(tmp_path / "original")
    ref = await original.save_once(value)
    os.rename(original.root, tmp_path / "retained-root")
    original.root.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="inode"):
        await original.load_exact(ref, value.identity)


@pytest.mark.parametrize(
    "field",
    ["task_id", "trace_id", "original_intent_fence", "spec_sha256", "execution_method_sha256"],
)
async def test_wrong_original_identity_cannot_load_metadata(tmp_path: Path, field: str) -> None:
    from uuid import UUID

    value = diagnostic()
    store = ContainmentDiagnosticStore(tmp_path / "diagnostics")
    ref = await store.save_once(value)
    changed = (
        2
        if field == "original_intent_fence"
        else UUID(int=8)
        if field.endswith("_id")
        else "f" * 64
    )
    copied = value.identity.model_copy(update={field: changed})
    with pytest.raises(ValueError):
        await store.load_exact(ref, copied)


@pytest.mark.parametrize("change", [{"first": "missing"}, {"omitted": 1}, {"total": 1}])
def test_sample_summary_cannot_invent_or_omit_endpoints(change: dict[str, object]) -> None:
    from nexus.builder.contained_diagnostics import SampleTrace

    raw = diagnostic().samples.model_dump() | change
    with pytest.raises(ValueError):
        SampleTrace.model_validate(raw)


@pytest.mark.parametrize("value", [b"x" * 4097, b"x" * 65537])
def test_inspect_prefix_is_never_an_unbounded_body(value: bytes) -> None:
    import base64

    from nexus.builder.contained_diagnostics import StreamObservation

    with pytest.raises(ValueError):
        StreamObservation(
            observed_bytes=len(value),
            observed_sha256=hashlib.sha256(value).hexdigest(),
            prefix_base64=base64.b64encode(value).decode(),
            complete=True,
            overflow=False,
            byte_limit=65536,
        )
