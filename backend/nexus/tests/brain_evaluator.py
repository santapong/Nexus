"""Original thirty-case evaluator with immutable fixture identity and fail-closed receipts."""

from __future__ import annotations

import hashlib
from pathlib import Path

from nexus.tests.brain_evaluation_assertions import assertion
from nexus.tests.brain_evaluation_contracts import (
    CaseObservation,
    CaseReceipt,
    ClauseReceipt,
    EvaluationReceipt,
    GoldenCase,
    GoldenPack,
    StructuredAnswer,
    fingerprint,
)
from nexus.tests.brain_source_fixtures import (
    FIXTURES,
    QUESTION_SHA256,
    SOURCE_SHA256,
    frozen_sources,
)

GOLDEN_SHA256 = "acd79916193b308760dafa24e4c3be6e04f8104f1f128f14fa52a8cc569a004d"
MANIFEST_SHA256 = "2fc3de2da9cdd5d51811df9d9d008f403ba24cba5b96377d4271c5b460e616d1"
CONFIG_SHA256 = "2cc50f1f06d3a3f43ec60ed962d2861330b5f03c3d6e63726347ceb6ed13ab72"
CRITICAL = frozenset(
    {
        "B04",
        "B05",
        "B07",
        "B08",
        "B09",
        "B10",
        "B11",
        "B12",
        "B20",
        "B22",
        "B23",
        "B24",
        "B25",
        "B26",
        "B29",
        "B30",
    }
)


def _exact_file(path: Path, expected: str) -> bytes:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Frozen evaluator fixture changed")
    return raw


def frozen_goldens() -> GoldenPack:
    """Evaluator-only loading occurs after observations; this function is never a provider."""
    _exact_file(FIXTURES.parent / "company_v1" / "brain_cases.json", QUESTION_SHA256)
    _exact_file(FIXTURES / "sources.json", SOURCE_SHA256)
    _exact_file(FIXTURES / "manifest.json", MANIFEST_SHA256)
    pack = GoldenPack.model_validate_json(_exact_file(FIXTURES / "golden.json", GOLDEN_SHA256))
    if {row.case_id for row in pack.cases} != {f"B{number:02d}" for number in range(1, 31)}:
        raise ValueError("Frozen evaluator must contain the original thirty cases")
    if {row.case_id for row in pack.cases if row.critical} != CRITICAL:
        raise ValueError("Frozen critical case set changed")
    return pack


def _citation_consistency(observed: CaseObservation) -> bool:
    known = {row.record.evidence_id: row for row in observed.materialized}
    source_aliases = {row.evidence_id: row.source_alias for row in frozen_sources().evidence}
    if len(known) != len(observed.materialized):
        return False
    for citation in observed.answer.citations:
        item = known.get(citation.evidence_id)
        if item is None:
            return False
        if source_aliases.get(citation.evidence_id) != citation.source_alias:
            return False
        record = item.record
        if (
            citation.company_id,
            citation.artifact_id,
            citation.source_revision_id,
            citation.source_revision,
            citation.span_sha256,
            citation.locator.start_byte,
            citation.locator.end_byte,
        ) != (
            observed.company_id,
            record.artifact.artifact_id,
            record.source.source_revision_id,
            record.source.revision,
            record.span_sha256,
            record.raw_span.start_byte,
            record.raw_span.end_byte,
        ):
            return False
        if citation.locator.section != record.raw_span.section:
            return False
    return len({row.evidence_id for row in observed.answer.citations}) == len(
        observed.answer.citations
    )


def _context_consistency(observed: CaseObservation) -> bool:
    context, capture = observed.context, observed.sdk_request
    if capture.request_sha256 != hashlib.sha256(capture.request_json.encode()).hexdigest():
        return False
    if (capture.system_text, capture.input_text) != (context.system_text, context.input_text):
        return False
    materials = {row.record.evidence_id: row for row in observed.materialized}
    return all(
        row.handle.evidence_id in materials
        and row.handle.record == materials[row.handle.evidence_id].record
        and row.handle.contributors == materials[row.handle.evidence_id].contributors
        and row.handle.source_contributors == materials[row.handle.evidence_id].source_contributors
        for row in context.manifest.inclusions
    )


def _answer_consistency(observed: CaseObservation) -> bool:
    try:
        return (
            StructuredAnswer.model_validate_json(observed.sdk_request.response_text)
            == observed.answer
        )
    except ValueError:
        return False


def _state_consistency(observed: CaseObservation) -> bool:
    names = {
        "authority_state",
        "budget_state",
        "work_state",
        "claim_state",
        "relationship_state",
        "effect_state",
        "notification_state",
        "access_checks",
    }
    rows = tuple(row for row in observed.surfaces if row.name in names)
    return len(rows) == len(names) and all(row.before == row.after for row in rows)


def _checks(observed: CaseObservation, golden: GoldenCase) -> tuple[ClauseReceipt, ...]:
    expected = golden.expected_answer
    checks = {
        "fixture_identity": (
            observed.question_sha256 == golden.question_sha256
            and observed.input_sha256 == golden.input_sha256
            and observed.rubric_sha256 == golden.rubric_sha256
            and observed.source_pack_sha256 == SOURCE_SHA256
            and observed.configuration_sha256 == CONFIG_SHA256
        ),
        "same_company_principal": (
            observed.context.company_id == observed.company_id == observed.retrieval.company_id
            and observed.context.manifest.principal_id == observed.principal_id
            and all(row.company_id == observed.company_id for row in observed.materialized)
        ),
        "citations_resolve_exact_bytes": _citation_consistency(observed),
        "sdk_context_hash_and_inclusions": _context_consistency(observed),
        "sdk_answer_response_exact": _answer_consistency(observed),
        "all_actual_state_snapshots_unchanged": _state_consistency(observed),
        "status_facts_consistent": (
            observed.answer.status == expected.get("status")
            and observed.answer.facts == expected.get("facts")
        ),
        "render_consistent": observed.export_render == observed.answer.rendered(),
        "current_access_receipt_present": len(
            [row for row in observed.surfaces if row.name == "access_checks"]
        )
        == 1,
    }
    return tuple(
        ClauseReceipt(
            assertion_id=f"{golden.case_id}.generic.{name}",
            operation=name,
            passed=passed,
            reason="verified" if passed else "missing or inconsistent actual observation",
        )
        for name, passed in checks.items()
    )


def _case(golden: GoldenCase, observed: CaseObservation | None) -> CaseReceipt:
    if observed is None:
        return CaseReceipt(
            case_id=golden.case_id,
            critical=golden.critical,
            passed=False,
            generic_checks=(),
            clauses=tuple(
                ClauseReceipt(
                    assertion_id=row.assertion_id,
                    operation=row.operation,
                    passed=False,
                    reason="case observation missing",
                )
                for row in golden.assertions
            ),
            observation_sha256=None,
        )
    checks = _checks(observed, golden)
    clauses = []
    for clause in golden.assertions:
        try:
            passed = assertion(observed, clause)
        except (ValueError, TypeError, KeyError):
            passed = False
        clauses.append(
            ClauseReceipt(
                assertion_id=clause.assertion_id,
                operation=clause.operation,
                passed=passed,
                reason="verified" if passed else "rubric failed or observation missing",
            )
        )
    return CaseReceipt(
        case_id=golden.case_id,
        critical=golden.critical,
        passed=all(row.passed for row in (*checks, *clauses)),
        generic_checks=checks,
        clauses=tuple(clauses),
        observation_sha256=fingerprint(observed),
    )


def evaluate(observations: tuple[CaseObservation, ...]) -> EvaluationReceipt:
    """Missing/skipped cases produce failure rows; no denominator reduction or golden inference."""
    observations = tuple(
        CaseObservation.model_validate_json(row.model_dump_json()) for row in observations
    )
    if len({row.case_id for row in observations}) != len(observations):
        raise ValueError("Duplicate case observations cannot be scored")
    known = {row.case_id: row for row in observations}
    pack = frozen_goldens()
    if set(known) - {row.case_id for row in pack.cases}:
        raise ValueError("Foreign case observations cannot replace original v1 cases")
    rows = tuple(_case(golden, known.get(golden.case_id)) for golden in pack.cases)
    passed = sum(row.passed for row in rows)
    critical = sum(row.passed for row in rows if row.critical)
    return EvaluationReceipt(
        scope="synthetic_restricted_pg_offline_sdk_only",
        original_question_pack_sha256=QUESTION_SHA256,
        source_pack_sha256=SOURCE_SHA256,
        golden_pack_sha256=GOLDEN_SHA256,
        source_golden_manifest_sha256=MANIFEST_SHA256,
        configuration_sha256=CONFIG_SHA256,
        cases=rows,
        passed_count=passed,
        critical_passed_count=critical,
        threshold_passed=passed >= 27 and critical == 16,
    )
