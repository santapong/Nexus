"""Fail-closed parsing of legacy QA flags, without manufacturing acceptance evidence."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, JsonValue, StrictBool, TypeAdapter


class LegacyReviewDecision(BaseModel):
    """Only an explicit boolean can authorize the legacy QA result boundary."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    approved: StrictBool
    feedback: str = ""


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Ambiguous duplicate key in QA JSON")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError("Nonfinite QA JSON value")


def _decode_object(value: object) -> dict[str, JsonValue]:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("```"):
            if "\n" not in text or not text.endswith("```"):
                raise ValueError("Incomplete QA JSON fence")
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_nonfinite)
    parsed: JsonValue = TypeAdapter(JsonValue).validate_python(value)
    json.dumps(parsed, allow_nan=False)
    if not isinstance(parsed, dict):
        raise ValueError("QA decision must be a JSON object")
    return parsed


def parse_legacy_review(value: object) -> LegacyReviewDecision:
    """Reject missing/nonboolean approval, malformed JSON and duplicate keys.

    This parser verifies only the legacy flag's structure. It does not establish
    independent evidence, acceptance criteria, permission or company completion.
    """
    return LegacyReviewDecision.model_validate(_decode_object(value))


def parse_polled_review(value: object) -> LegacyReviewDecision:
    """Consume the actual legacy task result envelope without approving a fallback."""
    result = _decode_object(value)
    if "status" in result and result["status"] != "completed":
        raise ValueError("QA task did not complete successfully")
    if "approved" in result:
        if "output" in result or "qa_review" in result:
            raise ValueError("Ambiguous QA result envelope")
        return parse_legacy_review(result)
    output = _decode_object(result.get("output"))
    if "approved" in output and "qa_review" in output:
        raise ValueError("Ambiguous QA result envelope")
    if "qa_review" in output:
        return parse_legacy_review(output["qa_review"])
    return parse_legacy_review(output)
