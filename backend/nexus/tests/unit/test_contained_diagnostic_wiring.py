"""Bounded actual diagnostic persistence does not manufacture containment or receipts."""

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from nexus.builder.contained_diagnostic_wiring import persist_final, persist_raw
from nexus.builder.contained_diagnostics import (
    ContainmentDiagnosticStore,
    DiagnosticIdentity,
    FinalizationDiagnostic,
)
from nexus.builder.contained_evidence_types import ObservationDeadline
from nexus.builder.contained_process_contracts import ContainedRunCapture, RuntimeCapture
from nexus.builder.contained_services import ContainmentServices
from nexus.builder.process import ProcessCapture
from nexus.tests.contained_process_fixture import binding, parent
from nexus.tests.unit.test_contained_diagnostics import diagnostic


def raw_capture() -> ContainedRunCapture:
    return ContainedRunCapture(
        capture=ProcessCapture(b"", b"", 0, 1, None),
        runtime=RuntimeCapture(
            pid=777,
            start_ticks=7770,
            cgroup_path="/owned",
            parent_membership="observed_path",
            reap="waited",
        ),
        parent=parent(),
        deadline=ObservationDeadline(end_us=13_000_000),
        infrastructure="unproven",
    )


def services(tmp_path: Path) -> ContainmentServices:
    return cast(
        ContainmentServices,
        SimpleNamespace(
            diagnostics=ContainmentDiagnosticStore(tmp_path / "diagnostics"),
            deadline=ObservationDeadline(end_us=13_000_000),
        ),
    )


def original_identity() -> DiagnosticIdentity:
    return DiagnosticIdentity.model_validate(
        {key: getattr(binding(), key) for key in DiagnosticIdentity.model_fields}
    )


async def test_missing_raw_diagnostic_denies_before_any_persistence(tmp_path: Path) -> None:
    value = services(tmp_path)
    with pytest.raises(ValueError, match="diagnostic"):
        await persist_raw(raw_capture(), original_identity(), value)
    assert list(value.diagnostics.root.iterdir()) == []


async def test_original_raw_record_and_final_unknown_are_separate_actual_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nexus.builder.contained_diagnostic_wiring as module

    monkeypatch.setattr(module, "clock_us", lambda: 12_040_000)
    raw = raw_capture()
    record = diagnostic().model_copy(
        update={"parent_sha256": hashlib.sha256(raw.parent.model_dump_json().encode()).hexdigest()}
    )
    raw = raw.model_copy(update={"diagnostic": record})
    value = services(tmp_path)
    reference = await persist_raw(raw, original_identity(), value)
    assert await value.diagnostics.load_exact(reference, original_identity()) == record
    final = FinalizationDiagnostic(
        identity=original_identity(),
        status="unproven",
        diagnostics=("no_samples",),
        sample_count=0,
        sample_chain_sha256=hashlib.sha256(b"").hexdigest(),
    )
    second = await persist_final(final, value)
    assert (
        second.phase == "final"
        and await value.diagnostics.load_exact(second, original_identity()) == final
    )
    assert len(list(value.diagnostics.root.iterdir())) == 2


@pytest.mark.parametrize(
    "splice", ["identity", "deadline", "output", "runtime", "infrastructure", "samples"]
)
async def test_spliced_raw_metadata_denies_before_durable_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, splice: str
) -> None:
    import nexus.builder.contained_diagnostic_wiring as module

    monkeypatch.setattr(module, "clock_us", lambda: 12_040_000)
    raw = raw_capture()
    record = diagnostic().model_copy(
        update={"parent_sha256": hashlib.sha256(raw.parent.model_dump_json().encode()).hexdigest()}
    )
    replacements = {
        "identity": record.identity.model_copy(update={"original_intent_fence": 99}),
        "deadline": 12_999_999,
        "output": record.stdout.model_copy(update={"observed_bytes": 1}),
        "runtime": record.runtime.model_copy(update={"pid": 778}),
        "infrastructure": "known",
        "samples": record.samples.model_copy(update={"chain_sha256": "f" * 64}),
    }
    fields = {
        "identity": "identity",
        "deadline": "deadline_end_us",
        "output": "stdout",
        "runtime": "runtime",
        "infrastructure": "infrastructure",
        "samples": "samples",
    }
    record = record.model_copy(update={fields[splice]: replacements[splice]})
    value = services(tmp_path)
    with pytest.raises(ValueError, match="diagnostic"):
        await persist_raw(raw.model_copy(update={"diagnostic": record}), original_identity(), value)
    assert list(value.diagnostics.root.iterdir()) == []


async def test_late_store_cannot_extend_original_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import nexus.builder.contained_diagnostic_wiring as module

    clocks = iter((12_040_000, 13_000_001))
    monkeypatch.setattr(module, "clock_us", clocks.__next__)
    value = services(tmp_path)
    final = FinalizationDiagnostic(
        identity=original_identity(),
        status="unproven",
        diagnostics=("no_samples",),
        sample_count=0,
        sample_chain_sha256=hashlib.sha256(b"").hexdigest(),
    )
    with pytest.raises(ValueError, match=r"original.*end"):
        await persist_final(final, value)
    assert len(list(value.diagnostics.root.iterdir())) == 1


def test_new_method_contract_does_not_reuse_first_untraced_job_identity() -> None:
    from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256

    assert (
        CONTAINED_EXECUTION_METHOD_SHA256
        != "33c3c1840b812d73392455ea3120e41a5fb662e74e0274060f0443348235fa13"
    )


def test_parent_failure_metadata_requires_a_new_complete_method_identity() -> None:
    from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256

    assert CONTAINED_EXECUTION_METHOD_SHA256 not in {
        "1a078eb321e81b58efb44e20a59af35716c6b47988c925adabc90d9107f22c79",
        "38fcb407e39abcda6a0352678fc9aa98254d66eadaa1d7d4543575775e4df04b",
    }


def test_issued_membership_requires_a_new_complete_method_identity() -> None:
    from nexus.builder.execution_method import CONTAINED_EXECUTION_METHOD_SHA256

    assert CONTAINED_EXECUTION_METHOD_SHA256 != (
        "36ab659fa81c0adc21f016a7d7f3263c73a5cc924a418a2925dc245df7f6d78b"
    )


def test_services_keep_diagnostic_storage_separate_from_success_sidecars(tmp_path: Path) -> None:
    from nexus.builder.contained_evidence_store import ContainmentEvidenceStore

    value = ContainmentServices(
        parent().expectation, ContainmentEvidenceStore(tmp_path / "sidecars")
    )
    assert type(value.diagnostics) is ContainmentDiagnosticStore
    assert value.diagnostics.root != value.store.root
    assert value.diagnostics.root.stat().st_mode & 0o777 == 0o700
