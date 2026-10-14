"""Native renderer preserves actual source text/time and ledger uncertainty."""

from nexus.company.management.check_contracts import ReportCheckInput
from nexus.company.management.report_checker import check_internal_report
from nexus.company.management.report_renderer import render_native_report
from nexus.tests.unit.test_company_management_checker import actual_report as actual_report


def test_rendered_actual_sources_and_native_projection_meet_declared_mechanical_criteria(
    actual_report: ReportCheckInput,
) -> None:
    assert actual_report.snapshot is not None and actual_report.snapshot.operating is not None
    report = render_native_report(
        actual_report.snapshot.operating,
        actual_report.snapshot.citations,
        observed_at=actual_report.snapshot.observed_at,
    )
    raw = report.model_dump_json().encode()
    import hashlib

    output = actual_report.output.model_copy(
        update={"sha256": hashlib.sha256(raw).hexdigest(), "byte_length": len(raw)}
    )
    command = actual_report.model_copy(
        update={
            "output": output,
            "output_utf8": raw,
            "target": actual_report.target.model_copy(update={"artifacts": (output,)}),
        }
    )
    assert check_internal_report(command).verdict == "pass"
    assert report.operating == actual_report.snapshot.operating


def test_missing_sources_cannot_render_an_invented_company_report(
    actual_report: ReportCheckInput,
) -> None:
    import pytest

    assert actual_report.snapshot is not None and actual_report.snapshot.operating is not None
    with pytest.raises(ValueError):
        render_native_report(
            actual_report.snapshot.operating, (), observed_at=actual_report.snapshot.observed_at
        )
