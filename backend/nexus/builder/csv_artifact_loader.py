"""Recompute CSV behavior from complete actual native capture bytes and protected witnesses."""

from __future__ import annotations

import base64
import hashlib

from nexus.builder.csv_behavior_wrapper import CASES, qualify_csv_observed_reports
from nexus.builder.csv_observation import REPORT_PATHS, qualify_csv_observations
from nexus.builder.csv_report_contracts import CsvBehaviorEvidence, CsvRecordedReports
from nexus.builder.csv_source_checks import observed_csv_sources
from nexus.builder.engineering_contracts import EngineeringCheckInput, EngineeringVerdict
from nexus.builder.execution_contracts import BuilderRunResult
from nexus.builder.node_v4_assets import csv_wrapper_source


def actual_csv_behavior(
    value: EngineeringCheckInput,
) -> tuple[CsvBehaviorEvidence, CsvBehaviorEvidence]:
    """Descriptions only; RegisteredEngineeringInputs supplies actual protected native basis."""
    pins = value.declaration.csv_regression
    if pins is None or value.declaration.behavior_case_ids != tuple(row[0] for row in CASES):
        raise ValueError("CSV behavior declaration differs from the exact seven reviewed cases")
    outcomes = []
    for result, witness in (
        (value.author, value.author_witness),
        (value.verifier, value.verifier_witness),
    ):
        observed = observed_csv_sources(value, result, witness)
        reports = CsvRecordedReports(
            wrapper=csv_wrapper_source().encode(),
            **{role: _captured_report(result, path) for role, path in REPORT_PATHS.items()},
        )
        qualify_csv_observations(
            pins,
            observed,
            reports,
            _captured_report(result, "baseline/checks/csv-wrapper-observation.json"),
            _captured_report(result, "post/checks/csv-wrapper-observation.json"),
        )
        outcomes.append(qualify_csv_observed_reports(pins, observed, reports))
    return outcomes[0], outcomes[1]


def check_csv_behavior(value: EngineeringCheckInput) -> tuple[EngineeringVerdict, str]:
    """Neither self-reported behavior.json nor expected hashes can replace actual reports."""
    try:
        actual_csv_behavior(value)
    except (ValueError, UnicodeError, RecursionError):
        return "reject", "actual_csv_report_source_or_receipt_differs"
    return "pass", "independent_actual_full_csv_regression_reports_passed"


def _captured_report(result: BuilderRunResult, path: str) -> bytes:
    matching = tuple(row for row in result.artifacts if row.metadata.path == path)
    if len(matching) != 1 or not 0 < matching[0].metadata.byte_length <= 2097152:
        raise ValueError("Actual complete CSV report capture is unavailable")
    row = matching[0]
    raw = base64.b64decode(row.content_base64, validate=True)
    if (
        len(raw) != row.metadata.byte_length
        or hashlib.sha256(raw).hexdigest() != row.metadata.sha256
    ):
        raise ValueError("CSV captured report bytes differ from native metadata")
    return raw
