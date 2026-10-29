"""Integrity checks reject protected results that are ambiguous or inapplicable."""

from __future__ import annotations

import hashlib

import pytest

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.management.acceptance_evidence import validate_report_result
from nexus.company.management.check_contracts import ReportCheckInput
from nexus.tests.unit.test_company_management_acceptance_evidence import protected

pytest_plugins = ("nexus.tests.unit.test_company_management_checker",)


def reference_for(reference: ArtifactRevisionRef, raw: bytes) -> ArtifactRevisionRef:
    """Bind even malformed bytes to their real digest to test decoding independently."""
    return reference.model_copy(
        update={"byte_length": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    )


@pytest.mark.parametrize("raw", [b"\xff", b"not json", b"{}"])
def test_integrity_matching_malformed_protected_result_is_denied(
    actual_report: ReportCheckInput, raw: bytes
) -> None:
    reference, _ = protected(actual_report)
    with pytest.raises(AcceptanceDeniedError, match="format is unavailable"):
        validate_report_result(actual_report, reference_for(reference, raw), raw)


def test_duplicate_json_key_is_denied_even_with_matching_artifact_digest(
    actual_report: ReportCheckInput,
) -> None:
    reference, raw = protected(actual_report)
    duplicate = b'{"verdict":"pass",' + raw[1:]
    with pytest.raises(AcceptanceDeniedError, match="format is unavailable"):
        validate_report_result(actual_report, reference_for(reference, duplicate), duplicate)


def test_unknown_check_recipe_cannot_reuse_valid_protected_result(
    actual_report: ReportCheckInput,
) -> None:
    reference, raw = protected(actual_report)
    wrong_target = actual_report.target.model_copy(update={"check_recipe": "unrecognized-v2"})
    command = actual_report.model_copy(update={"target": wrong_target})
    with pytest.raises(AcceptanceDeniedError, match="result is unavailable"):
        validate_report_result(command, reference, raw)
