"""Bounded deterministic CSV report qualification; no runner, side effect or acceptance."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from nexus.builder.csv_report_contracts import (
    CsvBehaviorCase,
    CsvBehaviorEvidence,
    CsvCapturedInputs,
    CsvObservedSources,
    CsvRecordedReports,
    CsvRegressionPins,
    CsvReportDigest,
    ReportRole,
    VitestAssertion,
    VitestFile,
    VitestReport,
    VitestSnapshot,
)

CSV_FILE = "src/csv/csv.test.ts"
PROBE_FILE = "src/.nexus-csv-before/csv.test.ts"
CSV_SUITE = ("csv mapper", "quantity contract v1")
CASES: tuple[tuple[str, str, Literal["passed", "failed"]], ...] = (
    (
        "csv.quantity.valid.v1",
        "accepts trimmed safe integers and preserves folding",
        "passed",
    ),
    (
        "csv.quantity.nonnumeric.v1",
        "rejects nonnumeric empty and missing quantities",
        "failed",
    ),
    (
        "csv.quantity.fractional.v1",
        "rejects fractional exponential and signed syntax",
        "failed",
    ),
    ("csv.quantity.trailing.v1", "rejects trailing quantity text", "failed"),
    ("csv.quantity.infinity.v1", "rejects nonfinite quantity text", "failed"),
    ("csv.quantity.unsafe.v1", "rejects unsafe integer quantities", "failed"),
    ("csv.quantity.zero.v1", "rejects zero and negative quantities", "passed"),
)
LEGACY_TITLES = (
    "folds multiple Shopee rows into one order with multiple lines",
    "skips rows with missing/zero quantity or subtotal and counts them",
    "counts rows dropped for missing order number or unparseable date",
    "handles Lazada column names",
)
ROLES: tuple[ReportRole, ...] = (
    "baseline_shared",
    "baseline_web",
    "before_probe",
    "post_shared",
    "post_web",
)


def mapping_sha256() -> str:
    """Pin seven exact names/statuses, legacy tests and fixed module/probe paths."""
    return _digest(
        json.dumps(
            {
                "cases": CASES,
                "legacy": LEGACY_TITLES,
                "suite": CSV_SUITE,
                "module": CSV_FILE,
                "probe": PROBE_FILE,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def qualify_csv_reports(pins: CsvRegressionPins, inputs: CsvCapturedInputs) -> CsvBehaviorEvidence:
    """Recompute all source/report pins and exact intended regression behavior."""
    pins = CsvRegressionPins.model_validate(
        {name: getattr(pins, name) for name in CsvRegressionPins.model_fields}
    )
    inputs = CsvCapturedInputs.model_validate(
        {name: getattr(inputs, name) for name in CsvCapturedInputs.model_fields}
    )
    _source_pins(pins, inputs)
    observed = CsvObservedSources(
        **{
            name + "_sha256": _digest(getattr(inputs, name))
            for name in ("baseline_module", "post_module", "baseline_test", "post_test")
        }
    )
    reports = CsvRecordedReports(
        wrapper=inputs.wrapper, **{role: getattr(inputs, role) for role in ROLES}
    )
    return qualify_csv_observed_reports(pins, observed, reports)


def qualify_csv_observed_reports(
    pins: CsvRegressionPins, observed: CsvObservedSources, inputs: CsvRecordedReports
) -> CsvBehaviorEvidence:
    """Separate digest API; production must first license actual protected native witnesses."""
    pins = CsvRegressionPins.model_validate(
        {name: getattr(pins, name) for name in CsvRegressionPins.model_fields}
    )
    observed = CsvObservedSources.model_validate(
        {name: getattr(observed, name) for name in CsvObservedSources.model_fields}
    )
    inputs = CsvRecordedReports.model_validate(
        {name: getattr(inputs, name) for name in CsvRecordedReports.model_fields}
    )
    _require(
        pins.mapping_sha256 == mapping_sha256() and _digest(inputs.wrapper) == pins.wrapper_sha256
    )
    _require(
        all(
            getattr(observed, name) == getattr(pins, name)
            for name in CsvObservedSources.model_fields
        )
    )
    _require(observed.baseline_module_sha256 != observed.post_module_sha256)
    _require(observed.baseline_test_sha256 != observed.post_test_sha256)
    _require(CSV_FILE in pins.shared_test_files)
    reports = tuple(_report(getattr(inputs, role)) for role in ROLES)
    for role, report in zip(ROLES, reports, strict=True):
        _report_paths(pins, role, report)
        _complete(report, expected_failure=role == "before_probe")
    _baseline_csv(reports[0])
    before, post = _csv(reports[2], PROBE_FILE), _csv(reports[3], CSV_FILE)
    _exact_csv(before, before=True)
    _exact_csv(post, before=False)
    return _result(pins, inputs, reports)


def _result(
    pins: CsvRegressionPins, inputs: CsvRecordedReports, reports: tuple[VitestReport, ...]
) -> CsvBehaviorEvidence:
    return CsvBehaviorEvidence(
        pins_sha256=_digest(pins.model_dump_json().encode()),
        source_and_method=pins,
        reports=tuple(
            CsvReportDigest(
                role=role,
                sha256=_digest(getattr(inputs, role)),
                byte_length=len(getattr(inputs, role)),
                assertions=report.numTotalTests,
            )
            for role, report in zip(ROLES, reports, strict=True)
        ),
        cases=tuple(
            CsvBehaviorCase(
                case_id=key,
                full_name=" ".join((*CSV_SUITE, title)),
                before_status=state,
            )
            for key, title, state in CASES
        ),
    )


def _source_pins(pins: CsvRegressionPins, value: CsvCapturedInputs) -> None:
    _require(pins.mapping_sha256 == mapping_sha256())
    for name in (
        "baseline_module",
        "post_module",
        "baseline_test",
        "post_test",
        "wrapper",
    ):
        _require(_digest(getattr(value, name)) == getattr(pins, name + "_sha256"))
    _require(pins.baseline_module_sha256 != pins.post_module_sha256)
    _require(pins.baseline_test_sha256 != pins.post_test_sha256)
    _require(CSV_FILE in pins.shared_test_files)


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("CSV report contains a non-JSON number")


def _report(raw: bytes) -> VitestReport:
    _require(0 < len(raw) <= 2097152)
    try:
        json.loads(raw, object_pairs_hook=_unique, parse_constant=_invalid_constant)
        return VitestReport.model_validate_json(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("CSV report/source qualification is unavailable") from None


def _report_paths(pins: CsvRegressionPins, role: str, report: VitestReport) -> None:
    phase = "baseline" if role.startswith("baseline_") else "post"
    package = "apps/web" if role.endswith("_web") else "packages/shared"
    expected = (
        (PROBE_FILE,)
        if role == "before_probe"
        else (pins.web_test_files if package == "apps/web" else pins.shared_test_files)
    )
    actual = tuple(sorted(file.name for file in report.testResults))
    _require(actual == tuple(f"/scratch/work/{phase}/{package}/{path}" for path in expected))


def _complete(report: VitestReport, *, expected_failure: bool) -> None:
    assertions = tuple(row for file in report.testResults for row in file.assertionResults)
    _require(0 < len(assertions) <= 10000)
    _require(report.numTotalTests == len(assertions))
    _require(report.numPassedTests == sum(row.status == "passed" for row in assertions))
    _require(report.numFailedTests == sum(row.status == "failed" for row in assertions))
    _require(report.numPendingTests == report.numTodoTests == report.numPendingTestSuites == 0)
    _require(
        report.numTotalTestSuites > 0
        and report.numTotalTestSuites
        == (report.numPassedTestSuites + report.numFailedTestSuites + report.numPendingTestSuites)
    )
    _require(report.success is (not expected_failure))
    _require((report.numFailedTests > 0) is expected_failure)
    _require((report.numFailedTestSuites > 0) is expected_failure)
    for file in report.testResults:
        _complete_file(file, report.startTime)
    _snapshot(report.snapshot)


def _complete_file(file: VitestFile, started: float) -> None:
    _require(file.startTime >= started and file.endTime >= file.startTime)
    _require(file.message == "" and file.assertionResults)
    _require(len({row.fullName for row in file.assertionResults}) == len(file.assertionResults))
    _require(
        file.status
        == ("failed" if any(row.status == "failed" for row in file.assertionResults) else "passed")
    )
    for row in file.assertionResults:
        _require(row.status in {"passed", "failed"} and not row.meta)
        _require(row.fullName == " ".join((*row.ancestorTitles, row.title)))
        _require(bool(row.failureMessages) is (row.status == "failed"))


def _snapshot(snapshot: VitestSnapshot) -> None:
    _require(not snapshot.failure and not snapshot.didUpdate)
    _require(
        all(
            getattr(snapshot, name) == 0
            for name in (
                "added",
                "filesAdded",
                "filesRemoved",
                "filesUnmatched",
                "filesUpdated",
                "unchecked",
                "unmatched",
                "updated",
            )
        )
    )
    _require(not snapshot.filesRemovedList and not snapshot.uncheckedKeysByFile)
    _require(snapshot.total == snapshot.matched)


def _csv(report: VitestReport, relative: str) -> tuple[VitestAssertion, ...]:
    matches = tuple(file for file in report.testResults if file.name.endswith("/" + relative))
    _require(len(matches) == 1)
    return matches[0].assertionResults


def _baseline_csv(report: VitestReport) -> None:
    rows = _csv(report, CSV_FILE)
    _require(
        tuple(sorted(row.fullName for row in rows))
        == tuple(sorted("csv mapper " + title for title in LEGACY_TITLES))
    )
    _require(all(row.status == "passed" and row.ancestorTitles == ("csv mapper",) for row in rows))


def _exact_csv(rows: tuple[VitestAssertion, ...], *, before: bool) -> None:
    legacy = {"csv mapper " + title for title in LEGACY_TITLES}
    desired = {
        " ".join((*CSV_SUITE, title)): status if before else "passed" for _, title, status in CASES
    }
    _require({row.fullName for row in rows} == legacy | desired.keys())
    for row in rows:
        _require(row.status == desired.get(row.fullName, "passed"))
        _require(row.ancestorTitles == (CSV_SUITE if row.fullName in desired else ("csv mapper",)))


def _require(value: object) -> None:
    if not value:
        raise ValueError("CSV report/source qualification is unavailable")
