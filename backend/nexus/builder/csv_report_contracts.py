"""Closed Vitest2.1.9 report decoding, with no process or publication authority."""

# ruff: noqa: N815 -- exact pinned upstream JSON field names preserve reporter wire compatibility.

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
)

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, StringConstraints(max_length=16384)]
Count = Annotated[int, Field(ge=0, le=100000, strict=True)]
ReportRole = Literal["baseline_shared", "baseline_web", "before_probe", "post_shared", "post_web"]
SourceBytes = Annotated[bytes, Field(min_length=1, max_length=1048576)]
ReportBytes = Annotated[bytes, Field(min_length=1, max_length=2097152)]


class CsvValue(BaseModel):
    """Only pinned typed descriptions cross this prototype boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class AssertionLocation(CsvValue):
    """Optional actual reporter location, never inferred from an assertion name."""

    line: Count
    column: Count


class VitestAssertion(CsvValue):
    """Exact reporter assertion names/status and bounded diagnostics."""

    ancestorTitles: tuple[Text, ...] = Field(max_length=32)
    fullName: Text
    title: Text
    status: Literal["passed", "failed", "skipped", "pending", "todo", "disabled"]
    meta: dict[str, JsonValue]
    failureMessages: tuple[Text, ...] | None = Field(max_length=32)
    duration: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    location: AssertionLocation | None = None


class VitestFile(CsvValue):
    """A complete named module result, containing bounded actual assertion results."""

    message: Text
    name: Text
    status: Literal["failed", "passed"]
    startTime: float = Field(ge=0, le=9007199254740991, allow_inf_nan=False)
    endTime: float = Field(ge=0, le=9007199254740991, allow_inf_nan=False)
    assertionResults: tuple[VitestAssertion, ...] = Field(max_length=10000)


class SnapshotKeys(CsvValue):
    """Known optional snapshot unchecked-key summary."""

    filePath: Text
    keys: tuple[Text, ...] = Field(max_length=10000)


class VitestSnapshot(CsvValue):
    """Pinned snapshot summary fields; unchecked/updated/failing snapshots cannot qualify."""

    added: Count
    failure: bool
    filesAdded: Count
    filesRemoved: Count
    filesRemovedList: tuple[Text, ...] = Field(max_length=1000)
    filesUnmatched: Count
    filesUpdated: Count
    matched: Count
    total: Count
    unchecked: Count
    uncheckedKeysByFile: tuple[SnapshotKeys, ...] = Field(max_length=1000)
    unmatched: Count
    updated: Count
    didUpdate: bool


class VitestReport(CsvValue):
    """Strict version-specific JSON reporter layout, independent of exit-code claims."""

    numFailedTests: Count
    numFailedTestSuites: Count
    numPassedTests: Count
    numPassedTestSuites: Count
    numPendingTests: Count
    numPendingTestSuites: Count
    numTodoTests: Count
    numTotalTests: Count
    numTotalTestSuites: Count
    startTime: float = Field(ge=0, le=9007199254740991, allow_inf_nan=False)
    success: bool
    testResults: tuple[VitestFile, ...] = Field(min_length=1, max_length=1000)
    snapshot: VitestSnapshot


class CsvRegressionPins(CsvValue):
    """Required reviewed source/method pins; no unknown post hash can activate a job."""

    schema_version: Literal["nexus.builder.csv-regression.v1"] = "nexus.builder.csv-regression.v1"
    reporter_version: Literal["vitest2.1.9"] = "vitest2.1.9"
    baseline_module_sha256: Digest
    post_module_sha256: Digest
    baseline_test_sha256: Digest
    post_test_sha256: Digest
    mapping_sha256: Digest
    wrapper_sha256: Digest
    shared_test_files: tuple[Text, ...] = Field(min_length=1, max_length=1000)
    web_test_files: tuple[Text, ...] = Field(min_length=1, max_length=1000)

    @field_validator("shared_test_files", "web_test_files")
    @classmethod
    def exact_test_inventory(cls, paths: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(paths))) != paths:
            raise ValueError("CSV report test inventory must be sorted and distinct")
        for value in paths:
            path = PurePosixPath(value)
            if (
                len(value) > 512
                or path.is_absolute()
                or str(path) != value
                or ".." in path.parts
                or any(ord(char) < 32 for char in value)
                or "\\" in value
                or not value.endswith((".test.ts", ".test.tsx"))
            ):
                raise ValueError("CSV report inventory needs exact ordinary test paths")
        return paths


class CsvCapturedInputs(CsvValue):
    """Actual captured ordinary bytes; trusted runtime must supply their role/source binding."""

    baseline_module: SourceBytes
    post_module: SourceBytes
    baseline_test: SourceBytes
    post_test: SourceBytes
    wrapper: SourceBytes
    baseline_shared: ReportBytes
    baseline_web: ReportBytes
    before_probe: ReportBytes
    post_shared: ReportBytes
    post_web: ReportBytes


class CsvReportDigest(CsvValue):
    """Actual bytes/hash and the closed runtime role, with no caller-selected path."""

    role: ReportRole
    sha256: Digest
    byte_length: int = Field(ge=1, le=2097152, strict=True)
    assertions: int = Field(ge=1, le=10000, strict=True)


class CsvBehaviorCase(CsvValue):
    """A precisely mapped intended before status and actual post pass."""

    case_id: Text
    full_name: Text
    before_status: Literal["passed", "failed"]
    post_status: Literal["passed"] = "passed"


class CsvBehaviorEvidence(CsvValue):
    """Recomputed descriptive evidence, never an operative acceptance record."""

    schema_version: Literal["nexus.builder.csv-behavior.v1"] = "nexus.builder.csv-behavior.v1"
    pins_sha256: Digest
    source_and_method: CsvRegressionPins
    reports: tuple[CsvReportDigest, ...] = Field(min_length=5, max_length=5)
    cases: tuple[CsvBehaviorCase, ...] = Field(min_length=7, max_length=7)
    limitation: Literal["requires_actual_receipts_source_provenance_and_independent_acceptance"] = (
        "requires_actual_receipts_source_provenance_and_independent_acceptance"
    )


class CsvObservedSources(CsvValue):
    """Descriptive digests; only protected native witness lookup establishes observation."""

    baseline_module_sha256: Digest
    post_module_sha256: Digest
    baseline_test_sha256: Digest
    post_test_sha256: Digest


class CsvRecordedReports(CsvValue):
    """Actual complete captured bytes with fixed roles; no caller pass flags."""

    wrapper: SourceBytes
    baseline_shared: ReportBytes
    baseline_web: ReportBytes
    before_probe: ReportBytes
    post_shared: ReportBytes
    post_web: ReportBytes
