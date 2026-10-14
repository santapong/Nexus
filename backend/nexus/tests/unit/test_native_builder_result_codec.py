"""Captured command/runtime limits and bytes cannot become a fabricated successful result."""

import base64
import io
import tarfile
from datetime import UTC, datetime

import pytest

from nexus.builder.execution_contracts import BuilderExecutionSpec, BuilderRunResult
from nexus.builder.result_codec import captured, decode_runtime
from nexus.tests.builder_support import described_job


def observation(lines: list[str]) -> BuilderRunResult:
    spec = BuilderExecutionSpec(job=described_job(), policy_sha256="a" * 64)
    return decode_runtime(
        ("\n".join(lines) + "\n").encode(),
        spec,
        "b" * 64,
        1,
        "c" * 64,
        "nexus-builder-" + "d" * 32,
        datetime.now(UTC),
        1,
    )


@pytest.mark.parametrize(
    "case", ["zero_memory", "duplicate_log", "continued_failed", "duplicate_export"]
)
def test_invalid_actual_runtime_frames_cannot_pass(case: str) -> None:
    lines = ["NEXUS-BUILDER/1", "Q 4294967296 200000 100000 256", "C 0 0 1", "O 0 ", "E 0 ", "END"]
    if case == "zero_memory":
        lines[1] = "Q 0 200000 100000 256"
    if case == "duplicate_log":
        lines.insert(4, "O 0 ")
    if case == "continued_failed":
        lines[2] = "C 0 127 1"
        lines[-1:-1] = ["C 1 0 1", "O 1 ", "E 1 "]
    if case == "duplicate_export":
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            for phase in ("baseline", "post"):
                entry = tarfile.TarInfo(f"{phase}/checks/result.txt")
                entry.size = 1
                archive.addfile(entry, io.BytesIO(b"x"))
        encoded = base64.b64encode(stream.getvalue()).decode()
        lines[-1:-1] = ["C 1 0 1", "O 1 ", "E 1 ", "A " + encoded, "A " + encoded]
    with pytest.raises(ValueError):
        observation(lines)


def test_log_limit_and_artifact_export_failure_keep_actual_command_exit() -> None:
    prefix = ["NEXUS-BUILDER/1", "Q 4294967296 200000 100000 256", "C 0 0 1", "O 0 ", "E 0 "]
    limited = observation([*prefix, "R log_limit", "END"])
    assert limited.outcome == "resource_limited" and limited.commands[0].exit_code == 0
    failed = observation([*prefix, "C 1 0 1", "O 1 ", "E 1 ", "R artifact_export_failed", "END"])
    assert failed.outcome == "artifact_export_failed" and all(
        row.exit_code == 0 for row in failed.commands
    )


def test_captured_blob_mismatch_and_duplicate_paths_are_denied() -> None:
    row = captured("logs/0.out", b"actual")
    value = row.model_dump(mode="json")
    value["content_base64"] = base64.b64encode(b"fake").decode()
    with pytest.raises(ValueError):
        type(row).model_validate(value)
    result = observation(
        ["NEXUS-BUILDER/1", "Q 4294967296 200000 100000 256", "C 0 127 1", "O 0 ", "E 0 ", "END"]
    )
    value = result.model_dump(mode="json")
    value["logs"] = [row.model_dump(mode="json")] * 2
    with pytest.raises(ValueError):
        type(result).model_validate(value)
