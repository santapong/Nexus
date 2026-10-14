"""Synthetic bounded report inputs do not establish StockFlow process or acceptance authority."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest

# Any is limited to synthetic JSON fixtures, matching json.loads dynamic return values;
# the production boundary immediately validates closed Pydantic report models.
from nexus.builder.csv_behavior_wrapper import (
    CASES,
    CSV_FILE,
    CSV_SUITE,
    LEGACY_TITLES,
    PROBE_FILE,
    mapping_sha256,
    qualify_csv_reports,
)
from nexus.builder.csv_report_contracts import CsvCapturedInputs, CsvRegressionPins


def _row(title: str, *, legacy: bool = False, status: str = "passed") -> dict[str, Any]:
    parents = ("csv mapper",) if legacy else CSV_SUITE
    return {
        "ancestorTitles": list(parents),
        "fullName": " ".join((*parents, title)),
        "title": title,
        "status": status,
        "meta": {},
        "duration": 1,
        "failureMessages": ["AssertionError: intended quantity contract"]
        if status == "failed"
        else [],
    }


def _file(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": name,
        "message": "",
        "startTime": 2,
        "endTime": 3,
        "status": "failed" if any(row["status"] == "failed" for row in rows) else "passed",
        "assertionResults": rows,
    }


def _report(files: list[dict[str, Any]]) -> dict[str, Any]:
    assertions = [row for file in files for row in file["assertionResults"]]
    failed = sum(row["status"] == "failed" for row in assertions)
    snapshot: dict[str, Any] = dict.fromkeys(
        (
            "added",
            "filesAdded",
            "filesRemoved",
            "filesUnmatched",
            "filesUpdated",
            "matched",
            "total",
            "unchecked",
            "unmatched",
            "updated",
        ),
        0,
    )
    snapshot.update(
        {
            "failure": False,
            "didUpdate": False,
            "filesRemovedList": [],
            "uncheckedKeysByFile": [],
        }
    )
    return {
        "numFailedTests": failed,
        "numPassedTests": len(assertions) - failed,
        "numFailedTestSuites": int(failed > 0),
        "numPassedTestSuites": 4 - int(failed > 0),
        "numPendingTests": 0,
        "numPendingTestSuites": 0,
        "numTodoTests": 0,
        "numTotalTests": len(assertions),
        "numTotalTestSuites": 4,
        "startTime": 1,
        "success": not failed,
        "testResults": files,
        "snapshot": snapshot,
    }


def described_inputs() -> tuple[CsvRegressionPins, CsvCapturedInputs]:
    sources = {
        name: name.encode()
        for name in (
            "baseline_module",
            "post_module",
            "baseline_test",
            "post_test",
            "wrapper",
        )
    }
    shared = ("src/csv/csv.test.ts", "src/money/money.test.ts")
    web = ("lib/example.test.ts",)
    reports = {}
    legacy = [_row(title, legacy=True) for title in LEGACY_TITLES]
    for phase in ("baseline", "post"):
        csv = legacy if phase == "baseline" else [*legacy, *[_row(title) for _, title, _ in CASES]]
        base = f"/scratch/work/{phase}/packages/shared/"
        reports[phase + "_shared"] = json.dumps(
            _report(
                [
                    _file(base + CSV_FILE, csv),
                    _file(base + shared[1], [_row("other passing assertion")]),
                ]
            )
        ).encode()
        reports[phase + "_web"] = json.dumps(
            _report(
                [
                    _file(
                        f"/scratch/work/{phase}/apps/web/{web[0]}",
                        [_row("web assertion")],
                    )
                ]
            )
        ).encode()
    before = [*legacy, *[_row(title, status=status) for _, title, status in CASES]]
    reports["before_probe"] = json.dumps(
        _report([_file("/scratch/work/post/packages/shared/" + PROBE_FILE, before)])
    ).encode()
    pins = CsvRegressionPins.model_validate(
        {
            **{name + "_sha256": hashlib.sha256(raw).hexdigest() for name, raw in sources.items()},
            "mapping_sha256": mapping_sha256(),
            "shared_test_files": shared,
            "web_test_files": web,
        }
    )
    return pins, CsvCapturedInputs(**sources, **reports)


def _change_report(
    value: CsvCapturedInputs, role: str, report: dict[str, Any]
) -> CsvCapturedInputs:
    return value.model_copy(update={role: json.dumps(report).encode()})


def test_exact_seven_before_states_and_complete_post_reports_describe_only_evidence() -> None:
    pins, value = described_inputs()
    result = qualify_csv_reports(pins, value)
    assert len(result.cases) == 7 and len(result.reports) == 5
    assert sum(row.before_status == "failed" for row in result.cases) == 5
    assert all(row.post_status == "passed" for row in result.cases)
    assert (
        result.limitation == "requires_actual_receipts_source_provenance_and_independent_acceptance"
    )
    assert result.reports[0].assertions == 5  # Nested suite count4 is not file count2.


@pytest.mark.parametrize(
    "role",
    ["baseline_shared", "baseline_web", "before_probe", "post_shared", "post_web"],
)
def test_swapped_or_empty_role_report_cannot_qualify(role: str) -> None:
    pins, value = described_inputs()
    swapped = value.model_copy(update={role: value.baseline_web})
    if role == "baseline_web":
        swapped = value.model_copy(update={role: value.post_web})
    with pytest.raises(ValueError):
        qualify_csv_reports(pins, swapped)
    with pytest.raises(ValueError):
        qualify_csv_reports(pins, value.model_copy(update={role: b""}))


@pytest.mark.parametrize(
    "field", ["baseline_module", "post_module", "baseline_test", "post_test", "wrapper"]
)
def test_mutated_source_or_wrapper_pin_cannot_use_successful_report(field: str) -> None:
    pins, value = described_inputs()
    with pytest.raises(ValueError):
        qualify_csv_reports(pins, value.model_copy(update={field: b"different actual bytes"}))


@pytest.mark.parametrize("status", ["skipped", "pending", "todo", "disabled", "unknown"])
def test_nonexecuted_or_unknown_case_is_not_a_post_pass(status: str) -> None:
    pins, value = described_inputs()
    report = json.loads(value.post_shared)
    report["testResults"][0]["assertionResults"][4]["status"] = status
    with pytest.raises(ValueError):
        qualify_csv_reports(pins, _change_report(value, "post_shared", report))


@pytest.mark.parametrize(
    "failure",
    [
        "missing_case",
        "missing_file",
        "duplicate_case",
        "duplicate_file",
        "wrong_source",
        "wrong_name",
        "meta",
        "fake_pass_string",
    ],
)
def test_incomplete_duplicate_wrong_source_or_self_reported_case_cannot_qualify(
    failure: str,
) -> None:
    pins, value = described_inputs()
    report = json.loads(value.post_shared)
    file = report["testResults"][0]
    row = file["assertionResults"][4]
    if failure == "missing_case":
        file["assertionResults"].pop()
    if failure == "missing_file":
        report["testResults"].pop()
    if failure == "duplicate_case":
        file["assertionResults"].append(deepcopy(row))
    if failure == "duplicate_file":
        report["testResults"].append(deepcopy(file))
    if failure == "wrong_source":
        file["name"] = file["name"].replace("src/csv", "src/foreign")
    if failure == "wrong_name":
        row["fullName"] += " "
    if failure == "meta":
        row["meta"] = {"unsupported": "pass"}
    if failure == "fake_pass_string":
        report = {"cases": [{"case_id": key, "status": "pass"} for key, _, _ in CASES]}
    with pytest.raises(ValueError):
        qualify_csv_reports(pins, _change_report(value, "post_shared", report))


@pytest.mark.parametrize(
    "failure",
    [
        "unexpected_fail",
        "all_pass",
        "wrong_expected_case",
        "legacy_fail",
        "collection_error",
    ],
)
def test_before_probe_requires_intended_case_failures_and_preserved_legacy_passes(
    failure: str,
) -> None:
    pins, value = described_inputs()
    report = json.loads(value.before_probe)
    rows = report["testResults"][0]["assertionResults"]
    if failure == "unexpected_fail":
        rows[4]["status"] = "failed"
        rows[4]["failureMessages"] = ["unexpected"]
    if failure == "all_pass":
        for row in rows:
            row["status"] = "passed"
            row["failureMessages"] = []
    if failure == "wrong_expected_case":
        rows[5]["fullName"] = "csv mapper another intended failure"
    if failure == "legacy_fail":
        rows[0]["status"] = "failed"
        rows[0]["failureMessages"] = ["unrelated"]
    if failure == "collection_error":
        report["testResults"][0]["message"] = "import error"
    with pytest.raises(ValueError):
        qualify_csv_reports(pins, _change_report(value, "before_probe", report))


@pytest.mark.parametrize(
    "field",
    [
        "numTotalTests",
        "numPassedTests",
        "numFailedTests",
        "numTotalTestSuites",
        "numPendingTests",
        "numPendingTestSuites",
        "numTodoTests",
    ],
)
def test_report_counters_cannot_hide_unexecuted_assertions(field: str) -> None:
    pins, value = described_inputs()
    report = json.loads(value.post_shared)
    report[field] += 1
    with pytest.raises(ValueError):
        qualify_csv_reports(pins, _change_report(value, "post_shared", report))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"success":true,"success":false}',
        b'{"numTotalTests":NaN}',
        b"\xff",
        b" " * 2097153,
    ],
)
def test_duplicate_non_json_invalid_or_oversized_report_is_rejected(raw: bytes) -> None:
    pins, value = described_inputs()
    with pytest.raises(ValueError):
        qualify_csv_reports(pins, value.model_copy(update={"post_shared": raw}))


@pytest.mark.parametrize("bad", [False, True, 1.0, "1"])
def test_raw_counter_types_are_exact(bad: object) -> None:
    pins, value = described_inputs()
    report = json.loads(value.post_shared)
    report["numTotalTests"] = bad
    with pytest.raises(ValueError):
        qualify_csv_reports(pins, _change_report(value, "post_shared", report))


def test_unknown_report_shape_and_changed_mapping_do_not_qualify() -> None:
    pins, value = described_inputs()
    report = json.loads(value.post_shared)
    report["coverageMap"] = {}
    with pytest.raises(ValueError):
        qualify_csv_reports(pins, _change_report(value, "post_shared", report))
    with pytest.raises(ValueError):
        qualify_csv_reports(pins.model_copy(update={"mapping_sha256": "a" * 64}), value)


@pytest.mark.parametrize(
    "case", ["swapped_expected_failure", "legacy_failure", "missing_post_case"]
)
def test_consistent_counters_cannot_hide_wrong_regression_identity(case: str) -> None:
    pins, value = described_inputs()
    role = "post_shared" if case == "missing_post_case" else "before_probe"
    report = json.loads(getattr(value, role))
    rows = report["testResults"][0]["assertionResults"]
    if case == "swapped_expected_failure":
        rows[4]["status"], rows[5]["status"] = rows[5]["status"], rows[4]["status"]
        rows[4]["failureMessages"], rows[5]["failureMessages"] = (
            rows[5]["failureMessages"],
            rows[4]["failureMessages"],
        )
    if case == "legacy_failure":
        rows[0]["status"], rows[5]["status"] = rows[5]["status"], rows[0]["status"]
        rows[0]["failureMessages"], rows[5]["failureMessages"] = (
            rows[5]["failureMessages"],
            rows[0]["failureMessages"],
        )
    if case == "missing_post_case":
        rows.pop()
        report = _report(report["testResults"])
    with pytest.raises(ValueError):
        qualify_csv_reports(pins, _change_report(value, role, report))


def test_deep_or_unknown_json_returns_constant_denial_without_body_reflection() -> None:
    pins, value = described_inputs()
    for raw in (
        b"[" * 2000 + b"0" + b"]" * 2000,
        b'{"private":"synthetic-body-marker"}',
    ):
        with pytest.raises(
            ValueError, match=r"^CSV report/source qualification is unavailable$"
        ) as denied:
            qualify_csv_reports(pins, value.model_copy(update={"post_shared": raw}))
        assert "synthetic-body-marker" not in str(denied.value)
