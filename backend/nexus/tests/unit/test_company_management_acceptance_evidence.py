"""Protected result integrity is necessary, never sufficient for persistent acceptance."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_evidence import validate_report_result
from nexus.company.management.check_contracts import ReportCheckInput
from nexus.company.management.report_checker import check_internal_report
from nexus.tests.unit.test_company_management_checker import actual_report as actual_report


def protected(command: ReportCheckInput) -> tuple[ArtifactRevisionRef, bytes]:
    raw = check_internal_report(command).model_dump_json().encode()
    return ArtifactRevisionRef(
        company_id=command.company_id,
        artifact_id=uuid4(),
        artifact_revision_id=uuid4(),
        revision="mechanical-result-v1",
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
    ), raw


def test_actual_mechanical_result_matches_exact_input(actual_report: ReportCheckInput) -> None:
    reference, raw = protected(actual_report)
    assert validate_report_result(actual_report, reference, raw) == check_internal_report(
        actual_report
    )


@pytest.mark.parametrize("change", ["bytes", "hash", "length", "company"])
def test_changed_protected_result_reference_denies(
    actual_report: ReportCheckInput, change: str
) -> None:
    reference, raw = protected(actual_report)
    if change == "bytes":
        raw += b" "
    else:
        values: dict[str, dict[str, object]] = {
            "hash": {"sha256": "0" * 64},
            "length": {"byte_length": len(raw) + 1},
            "company": {"company_id": uuid4()},
        }
        reference = reference.model_copy(update=values[change])
    with pytest.raises(ValueError):
        validate_report_result(actual_report, reference, raw)


def test_integrity_of_a_decoded_verdict_cannot_substitute_for_actual_recompute(
    actual_report: ReportCheckInput,
) -> None:
    reference, raw = protected(actual_report)
    changed = actual_report.model_copy(update={"output_utf8": b"unrelated actual protected bytes"})
    with pytest.raises(ValueError):
        validate_report_result(changed, reference, raw)


def test_changed_current_input_snapshot_denies_old_valid_result(
    actual_report: ReportCheckInput,
) -> None:
    reference, raw = protected(actual_report)
    assert actual_report.snapshot is not None
    snapshot = actual_report.snapshot.model_copy(update={"citations": ()})
    changed = actual_report.model_copy(update={"snapshot": snapshot})
    with pytest.raises(ValueError):
        validate_report_result(changed, reference, raw)


def test_actual_missing_input_is_preserved_as_inconclusive(actual_report: ReportCheckInput) -> None:
    missing = actual_report.model_copy(update={"snapshot": None})
    reference, raw = protected(missing)
    result = validate_report_result(missing, reference, raw)
    assert result.verdict == "inconclusive" and result.input_snapshot_sha256 is None


def test_result_bound_is_checked_before_decoding(actual_report: ReportCheckInput) -> None:
    reference, _ = protected(actual_report)
    raw = b"x" * 16_385
    reference = reference.model_copy(
        update={"byte_length": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    )
    with pytest.raises(ValueError):
        validate_report_result(actual_report, reference, raw)
