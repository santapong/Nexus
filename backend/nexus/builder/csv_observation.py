"""Bind captured observations to report/source bytes; writable outputs are not authenticated."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field

from nexus.builder.csv_report_contracts import (
    CsvObservedSources,
    CsvRecordedReports,
    CsvRegressionPins,
    CsvValue,
    Digest,
    ReportRole,
    Text,
)

MAX_OBSERVATION_BYTES = 65536
REPORT_PATHS: dict[ReportRole, str] = {
    "baseline_shared": "baseline/checks/shared-vitest.json",
    "baseline_web": "baseline/checks/web-vitest.json",
    "before_probe": "post/checks/csv-before-vitest.json",
    "post_shared": "post/checks/shared-vitest.json",
    "post_web": "post/checks/web-vitest.json",
}


class CsvObservationSources(CsvValue):
    """Exact immutable source roles observed by the fixed wrapper."""

    baseline_module: Digest
    post_module: Digest
    baseline_test: Digest
    post_test: Digest


class CsvObservationReport(CsvValue):
    """Actual wrapper process exit and raw report identity, with fixed host-checked path."""

    path: Text
    sha256: Digest
    byte_length: int = Field(ge=1, le=2097152, strict=True)
    exit_code: int = Field(ge=0, le=1, strict=True)


class CsvWrapperObservation(CsvValue):
    """Complete captured fixed wrapper layout; this DTO supplies no publication authority."""

    schema_version: Literal["nexus.builder.csv-wrapper-observation.v1"]
    phase: Literal["baseline", "post"]
    pins_sha256: Digest
    source_hashes: CsvObservationSources
    reports: dict[ReportRole, CsvObservationReport] = Field(min_length=2, max_length=3)


def qualify_csv_observations(
    pins: CsvRegressionPins,
    observed: CsvObservedSources,
    reports: CsvRecordedReports,
    baseline: bytes,
    post: bytes,
) -> None:
    """Detect capture splices; code able to rewrite both outputs can still fabricate consistency."""
    pins_sha = hashlib.sha256(pins.model_dump_json().encode()).hexdigest()
    for phase, raw in (("baseline", baseline), ("post", post)):
        value = decode_csv_observation(raw)
        if value.phase != phase or value.pins_sha256 != pins_sha:
            raise ValueError("CSV observation differs from actual canonical staged pins/phase")
        for name in CsvObservationSources.model_fields:
            source = getattr(value.source_hashes, name)
            if source != getattr(observed, name + "_sha256") or source != getattr(
                pins, name + "_sha256"
            ):
                raise ValueError("CSV observation differs from protected source witness/pins")
        _qualify_reports(value, reports)


def _qualify_reports(value: CsvWrapperObservation, reports: CsvRecordedReports) -> None:
    expected = {
        role: path for role, path in REPORT_PATHS.items() if path.startswith(value.phase + "/")
    }
    if value.reports.keys() != expected.keys():
        raise ValueError("CSV observation report roles are incomplete or spliced")
    for role, path in expected.items():
        row, raw = value.reports[role], getattr(reports, role)
        if (row.path, row.sha256, row.byte_length, row.exit_code) != (
            "/outputs/" + path,
            hashlib.sha256(raw).hexdigest(),
            len(raw),
            1 if role == "before_probe" else 0,
        ):
            raise ValueError("CSV observation differs from actual report bytes/path/normal exit")


def decode_csv_observation(raw: bytes) -> CsvWrapperObservation:
    """Decode actual historical bytes without promoting them to production qualification."""
    if not 0 < len(raw) <= MAX_OBSERVATION_BYTES:
        raise ValueError("CSV observation exceeds bounded capture")
    try:
        json.loads(raw, object_pairs_hook=_unique, parse_constant=_invalid_constant)
        return CsvWrapperObservation.model_validate_json(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("CSV observation qualification is unavailable") from None


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("CSV observation contains duplicate fields")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("CSV observation contains a non-JSON number")
