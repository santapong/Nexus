"""Strict actual behavior assertion decoding; unsupported or skipped cases never pass."""

from __future__ import annotations

import base64
import json

from nexus.builder.engineering_contracts import (
    EngineeringBehaviorEvidence,
    EngineeringCheckInput,
    EngineeringVerdict,
)


def check_behavior(value: EngineeringCheckInput) -> tuple[EngineeringVerdict, str]:
    if value.declaration.csv_regression is not None:
        from nexus.builder.csv_artifact_loader import check_csv_behavior

        return check_csv_behavior(value)
    path = "post/" + value.declaration.behavior_artifact
    for result in (value.author, value.verifier):
        evidence = next((row for row in result.artifacts if row.metadata.path == path), None)
        if evidence is None or evidence.metadata.byte_length > 16384:
            return "inconclusive", "actual_behavior_evidence_unavailable"
        try:
            raw = base64.b64decode(evidence.content_base64, validate=True)
            json.loads(raw.decode(), object_pairs_hook=_unique)
            behavior = EngineeringBehaviorEvidence.model_validate_json(raw)
        except (ValueError, UnicodeError, RecursionError):
            return "inconclusive", "actual_behavior_format_unavailable"
        if tuple(row.case_id for row in behavior.cases) != value.declaration.behavior_case_ids:
            return "reject", "declared_behavior_assertions_differ"
        if any(row.status == "fail" for row in behavior.cases):
            return "reject", "actual_behavior_assertion_failed"
        if any(row.status != "pass" for row in behavior.cases):
            return "inconclusive", "actual_behavior_assertion_not_executed"
    return "pass", "independent_actual_behavior_assertions_passed"


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate engineering behavior key")
        value[key] = item
    return value
