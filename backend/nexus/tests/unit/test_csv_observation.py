"""Retained actual observations plus explicitly constructed canonical loader descriptions."""

import base64
import hashlib
import json

import pytest

from nexus.builder.csv_artifact_loader import actual_csv_behavior
from nexus.builder.csv_observation import REPORT_PATHS, decode_csv_observation
from nexus.builder.engineering_behavior import check_behavior
from nexus.builder.engineering_contracts import EngineeringCheckInput
from nexus.builder.result_codec import captured
from nexus.tests.node_v4_support import ROOT, described_v4_check


def replace_capture(value: bytes, path: str, check_role: str = "verifier") -> EngineeringCheckInput:
    """Rehash native capture metadata, representing a later sandbox output overwrite."""
    check = described_v4_check()
    result = getattr(check, check_role)
    rows = tuple(row for row in result.artifacts if row.metadata.path != path)
    return check.model_copy(
        update={check_role: result.model_copy(update={"artifacts": (*rows, captured(path, value))})}
    )


@pytest.mark.parametrize("phase", ["baseline", "post"])
@pytest.mark.parametrize("check_role", ["author", "verifier"])
def test_retained_historical_noncanonical_observation_denies_production(
    phase: str, check_role: str
) -> None:
    raw = (ROOT / f"{phase}-checks-csv-wrapper-observation.json").read_bytes()
    observation = json.loads(raw)
    check = described_v4_check()
    assert check.declaration.csv_regression is not None
    canonical = check.declaration.csv_regression.model_dump_json().encode()
    assert (
        observation["pins_sha256"] == hashlib.sha256((ROOT / "pins.json").read_bytes()).hexdigest()
    )
    assert observation["pins_sha256"] != hashlib.sha256(canonical).hexdigest()
    changed = replace_capture(raw, f"{phase}/checks/csv-wrapper-observation.json", check_role)
    assert check_behavior(changed)[0] == "reject"


@pytest.mark.parametrize(
    "path",
    [
        "baseline/checks/shared-vitest.json",
        "baseline/checks/web-vitest.json",
        "post/checks/csv-before-vitest.json",
        "post/checks/shared-vitest.json",
        "post/checks/web-vitest.json",
    ],
)
def test_report_overwritten_after_wrapper_with_new_valid_metadata_denies(path: str) -> None:
    check = described_v4_check()
    row = next(row for row in check.verifier.artifacts if row.metadata.path == path)
    raw = base64.b64decode(row.content_base64) + b"\n"
    # Whitespace preserves report assertions, while changing the recorded byte identity.
    assert check_behavior(replace_capture(raw, path))[0] == "reject"


@pytest.mark.parametrize("phase", ["baseline", "post"])
@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate_capture",
        "wrong_phase",
        "pins",
        "source",
        "path",
        "hash",
        "length",
        "exit",
        "missing_role",
        "extra_role",
        "unknown",
        "duplicate_json",
        "huge",
    ],
)
def test_observation_splices_fail_closed(phase: str, fault: str) -> None:
    check = described_v4_check()
    path = f"{phase}/checks/csv-wrapper-observation.json"
    rows = check.verifier.artifacts
    observation_row = next(row for row in rows if row.metadata.path == path)
    observation = json.loads(base64.b64decode(observation_row.content_base64))
    role = "baseline_shared" if phase == "baseline" else "before_probe"
    if fault == "missing":
        rows = tuple(row for row in rows if row != observation_row)
    elif fault == "duplicate_capture":
        rows = (*rows, observation_row)
    else:
        if fault == "wrong_phase":
            observation["phase"] = "post" if phase == "baseline" else "baseline"
        if fault == "pins":
            observation["pins_sha256"] = "a" * 64
        if fault == "source":
            observation["source_hashes"]["baseline_module"] = "a" * 64
        if fault == "path":
            observation["reports"][role]["path"] = "/outputs/post/checks/foreign.json"
        if fault == "hash":
            observation["reports"][role]["sha256"] = "a" * 64
        if fault == "length":
            observation["reports"][role]["byte_length"] += 1
        if fault == "exit":
            observation["reports"][role]["exit_code"] = 0 if phase == "post" else 1
        if fault == "missing_role":
            del observation["reports"][role]
        if fault == "extra_role":
            observation["reports"]["post_shared" if phase == "baseline" else "baseline_shared"] = (
                observation["reports"][role]
            )
        if fault == "unknown":
            observation["trusted"] = True
        raw = json.dumps(observation, separators=(",", ":")).encode()
        if fault == "duplicate_json":
            raw = raw[:-1] + b',"phase":"' + phase.encode() + b'"}'
        if fault == "huge":
            raw += b" " * 65536
        rows = tuple(row for row in rows if row != observation_row)
        rows = (*rows, captured(path, raw))
    changed = check.model_copy(
        update={"verifier": check.verifier.model_copy(update={"artifacts": rows})}
    )
    assert check_behavior(changed)[0] == "reject"


def test_canonical_observation_descriptions_still_qualify_actual_report_bytes() -> None:
    assert len(actual_csv_behavior(described_v4_check())) == 2


@pytest.mark.parametrize("phase", ["baseline", "post"])
def test_retained_actual_observation_records_actual_phase_reports_and_exit(phase: str) -> None:
    raw = (ROOT / f"{phase}-checks-csv-wrapper-observation.json").read_bytes()
    value = decode_csv_observation(raw)
    expected = {role: path for role, path in REPORT_PATHS.items() if path.startswith(phase + "/")}
    assert value.phase == phase and value.reports.keys() == expected.keys()
    for role, path in expected.items():
        report = (ROOT / path.replace("/", "-")).read_bytes()
        row = value.reports[role]
        assert (row.path, row.sha256, row.byte_length, row.exit_code) == (
            "/outputs/" + path,
            hashlib.sha256(report).hexdigest(),
            len(report),
            1 if role == "before_probe" else 0,
        )


@pytest.mark.parametrize("bad", [b"", b"null", b"{}", b"\xff", b"NaN", b"[" * 10000])
def test_observation_decoder_rejects_malformed_or_deep_json(bad: bytes) -> None:
    with pytest.raises(ValueError, match="CSV observation"):
        decode_csv_observation(bad)


@pytest.mark.parametrize("field", ["exit_code", "byte_length"])
def test_observation_integers_cannot_be_bool(field: str) -> None:
    check = described_v4_check()
    path = "post/checks/csv-wrapper-observation.json"
    row = next(row for row in check.verifier.artifacts if row.metadata.path == path)
    value = json.loads(base64.b64decode(row.content_base64))
    value["reports"]["before_probe"][field] = True
    assert check_behavior(replace_capture(json.dumps(value).encode(), path))[0] == "reject"


def test_jointly_rewritten_outputs_consistency_does_not_authenticate_test_truth() -> None:
    """Explicit limit: writable report and observation can be made jointly consistent."""
    check = described_v4_check()
    report_path = "post/checks/shared-vitest.json"
    observation_path = "post/checks/csv-wrapper-observation.json"
    report = next(row for row in check.verifier.artifacts if row.metadata.path == report_path)
    raw = base64.b64decode(report.content_base64) + b"\n"
    observation = next(
        row for row in check.verifier.artifacts if row.metadata.path == observation_path
    )
    value = json.loads(base64.b64decode(observation.content_base64))
    value["reports"]["post_shared"]["sha256"] = hashlib.sha256(raw).hexdigest()
    value["reports"]["post_shared"]["byte_length"] = len(raw)
    rows = tuple(
        row
        for row in check.verifier.artifacts
        if row.metadata.path not in {report_path, observation_path}
    )
    rows = (
        *rows,
        captured(report_path, raw),
        captured(observation_path, json.dumps(value).encode()),
    )
    changed = check.model_copy(
        update={"verifier": check.verifier.model_copy(update={"artifacts": rows})}
    )
    assert check_behavior(changed)[0] == "pass"
