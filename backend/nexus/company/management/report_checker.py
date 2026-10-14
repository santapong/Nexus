"""Pure exact report checks; no I/O, model, publication or trusted-acceptance actions."""

from __future__ import annotations

import hashlib
import json

from pydantic import ValidationError

from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import (
    REPORT_CHECK_CRITERIA,
    REPORT_CHECK_RECIPE,
    AcceptedWorkClaim,
    CheckVerdict,
    CitationCheckSource,
    CriterionCheckResult,
    ReportCheckInput,
    ReportCheckPayload,
    ReportCheckResult,
    SemanticClaim,
    SourceQuoteClaim,
    StructuredInternalReport,
)

_MAX_REPORT_BYTES = 262_144
_MAX_SOURCE_BYTES = 8_388_608


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _row(criterion_id: str, verdict: CheckVerdict, reason: str) -> CriterionCheckResult:
    return CriterionCheckResult(criterion_id=criterion_id, verdict=verdict, reason=reason)


def _result(
    command: ReportCheckInput, criteria: tuple[CriterionCheckResult, ...]
) -> ReportCheckResult:
    verdict: CheckVerdict = "pass"
    if any(row.verdict == "reject" for row in criteria):
        verdict = "reject"
    elif any(row.verdict == "inconclusive" for row in criteria):
        verdict = "inconclusive"
    payload = ReportCheckPayload(
        company_id=command.company_id,
        recipe=REPORT_CHECK_RECIPE,
        target_sha256=canonical_sha256(command.target),
        output_sha256=_digest(command.output_utf8) if command.output_utf8 is not None else None,
        input_snapshot_sha256=canonical_sha256(command.snapshot) if command.snapshot else None,
        verdict=verdict,
        criteria=criteria,
        limitations=("mechanical_report_only", "no_semantic_truth_or_acceptance_authority"),
    )
    return ReportCheckResult(**payload.model_dump(), result_sha256=canonical_sha256(payload))


def _failure(command: ReportCheckInput, verdict: CheckVerdict, reason: str) -> ReportCheckResult:
    return _result(
        command, tuple(_row(cid, verdict, reason) for cid in command.target.criterion_ids)
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _no_constant(value: str) -> object:
    raise ValueError("Non-finite JSON constant")


def _bounded_json(raw: bytes) -> StructuredInternalReport:
    # json.loads is an untyped JSON parser; only a strict Pydantic model crosses this boundary.
    value: object = json.loads(
        raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_no_constant
    )
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > 16 or nodes > 12_000:
            raise ValueError("Report JSON exceeds structural bounds")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return StructuredInternalReport.model_validate_json(raw)


def _source_integrity(source: CitationCheckSource) -> bool:
    evidence = source.evidence
    raw = source.raw_text.encode("utf-8")
    span = raw[evidence.raw_span.start_byte : evidence.raw_span.end_byte]
    return (
        "\x00" not in source.raw_text
        and len(raw) == evidence.artifact.byte_length
        and _digest(raw) == evidence.artifact.sha256
        and len(span) == evidence.raw_span.end_byte - evidence.raw_span.start_byte
        and _digest(span) == evidence.span_sha256
        and source.head.source_id == evidence.source.source_id
        and source.head.current.source_id == evidence.source.source_id
    )


def _citation_result(
    command: ReportCheckInput, report: StructuredInternalReport
) -> CriterionCheckResult:
    criterion = "report.citations.v1"
    assert command.snapshot is not None
    sources = {row.evidence.evidence_id: row for row in command.snapshot.citations}
    if len(sources) != len(command.snapshot.citations):
        return _row(criterion, "reject", "duplicate_source_evidence")
    if sum(len(row.raw_text.encode()) for row in sources.values()) > _MAX_SOURCE_BYTES:
        return _row(criterion, "reject", "source_bytes_exceed_bound")
    if any(not _source_integrity(source) for source in sources.values()):
        return _row(criterion, "reject", "source_hash_or_locator_mismatch")
    quotes = [claim for claim in report.claims if isinstance(claim, SourceQuoteClaim)]
    if not quotes:
        return _row(criterion, "inconclusive", "source_quote_missing")
    if len({claim.evidence_id for claim in quotes}) != len(quotes):
        return _row(criterion, "reject", "duplicate_report_citation")
    for claim in quotes:
        source = sources.get(claim.evidence_id)
        if source is None:
            return _row(criterion, "inconclusive", "protected_citation_missing")
        if not _citation_matches(command, claim, source):
            return _row(criterion, "reject", "citation_snapshot_mismatch")
    return _row(criterion, "pass", "exact_citations_match")


def _citation_matches(
    command: ReportCheckInput, claim: SourceQuoteClaim, source: CitationCheckSource
) -> bool:
    assert command.snapshot is not None
    evidence, head = source.evidence, source.head
    state = "current" if evidence.source == head.current else "historical"
    freshness = "fresh"
    if head.availability != "available":
        freshness = "unavailable"
    elif head.fresh_until is None:
        if source.source_policy is None or source.source_policy.freshness_seconds is not None:
            freshness = "stale"
    elif (
        source.source_policy is not None and source.source_policy.freshness_seconds is None
    ) or head.fresh_until <= command.snapshot.observed_at:
        freshness = "stale"
    raw = source.raw_text.encode()
    quoted = raw[evidence.raw_span.start_byte : evidence.raw_span.end_byte]
    return (
        claim.source_revision_id == evidence.source.source_revision_id
        and claim.artifact_revision_id == evidence.artifact.artifact_revision_id
        and claim.span_sha256 == evidence.span_sha256
        and claim.quote.encode() == quoted
        and claim.source_state == state
        and claim.freshness == freshness
        and head.observed_at <= command.snapshot.observed_at
        and evidence.ingested_at <= command.snapshot.observed_at
    )


def _time_result(
    command: ReportCheckInput, report: StructuredInternalReport
) -> CriterionCheckResult:
    criterion = "report.source-time.v1"
    assert command.snapshot is not None
    sources = {row.evidence.evidence_id: row for row in command.snapshot.citations}
    quotes = [claim for claim in report.claims if isinstance(claim, SourceQuoteClaim)]
    if not quotes:
        return _row(criterion, "inconclusive", "source_time_missing")
    for claim in quotes:
        source = sources.get(claim.evidence_id)
        if source is None:
            return _row(criterion, "inconclusive", "protected_source_time_missing")
        if claim.source_event != source.evidence.source_event:
            return _row(criterion, "reject", "exact_source_time_mismatch")
    return _row(criterion, "pass", "exact_source_time_matches")


def _basis_result(
    command: ReportCheckInput, report: StructuredInternalReport
) -> CriterionCheckResult:
    criterion = "report.claim-basis.v1"
    assert command.snapshot is not None
    operating = command.snapshot.operating
    if operating is None:
        return _row(criterion, "inconclusive", "protected_acceptance_snapshot_missing")
    accepted = {
        row.work.task_id: row.acceptance_id
        for row in operating.snapshot.work
        if row.acceptance == "accepted" and row.work.task_id in operating.accepted_task_ids
    }
    declarations = [claim for claim in report.claims if isinstance(claim, AcceptedWorkClaim)]
    if len({claim.task_id for claim in declarations}) != len(declarations):
        return _row(criterion, "reject", "duplicate_accepted_work_claim")
    if any(accepted.get(claim.task_id) != claim.acceptance_id for claim in declarations):
        return _row(criterion, "reject", "independent_acceptance_mismatch")
    if any(isinstance(claim, SemanticClaim) for claim in report.claims):
        return _row(criterion, "inconclusive", "unsupported_semantic_claim")
    return _row(criterion, "pass", "explicit_claim_basis_matches")


def _operating_results(
    command: ReportCheckInput, report: StructuredInternalReport
) -> tuple[CriterionCheckResult, CriterionCheckResult]:
    assert command.snapshot is not None
    expected = command.snapshot.operating
    if expected is None:
        return (
            _row("report.ledger.v1", "inconclusive", "protected_ledger_missing"),
            _row("report.status.v1", "inconclusive", "protected_status_missing"),
        )
    actual = report.operating
    ledger_matches = (
        actual.snapshot.ledger == expected.snapshot.ledger
        and actual.actual_total_usd == expected.actual_total_usd
        and actual.unknown_charge_ids == expected.unknown_charge_ids
    )
    status_matches = (
        actual.snapshot.model_dump(exclude={"ledger"})
        == expected.snapshot.model_dump(exclude={"ledger"})
        and actual.accepted_task_ids == expected.accepted_task_ids
        and actual.receipt_task_ids == expected.receipt_task_ids
        and actual.cancelled_task_ids == expected.cancelled_task_ids
    )
    return (
        _row(
            "report.ledger.v1",
            "pass" if ledger_matches else "reject",
            "exact_ledger_matches" if ledger_matches else "ledger_snapshot_mismatch",
        ),
        _row(
            "report.status.v1",
            "pass" if status_matches else "reject",
            "exact_status_matches" if status_matches else "status_snapshot_mismatch",
        ),
    )


def _preflight(command: ReportCheckInput) -> ReportCheckResult | None:
    declared = command.target.criterion_ids
    if command.target.check_recipe != REPORT_CHECK_RECIPE:
        return _failure(command, "inconclusive", "unsupported_check_recipe")
    if set(declared) != set(REPORT_CHECK_CRITERIA) or len(declared) != len(REPORT_CHECK_CRITERIA):
        return _result(
            command,
            tuple(
                _row(
                    cid,
                    "inconclusive",
                    "unsupported_criterion"
                    if cid not in REPORT_CHECK_CRITERIA
                    else "incomplete_registered_criteria",
                )
                for cid in declared
            ),
        )
    if command.output_utf8 is None or command.snapshot is None:
        return _failure(command, "inconclusive", "actual_input_missing")
    raw = command.output_utf8
    if (
        command.target.artifacts != (command.output,)
        or len(raw) != command.output.byte_length
        or _digest(raw) != command.output.sha256
        or not _registration_matches(command)
    ):
        return _failure(command, "reject", "exact_target_or_input_hash_mismatch")
    if not 0 < len(raw) <= _MAX_REPORT_BYTES:
        return _failure(command, "reject", "report_bytes_exceed_bound")
    return None


def _registration_matches(command: ReportCheckInput) -> bool:
    assert command.snapshot is not None
    snapshot, target = command.snapshot, command.target
    registration = snapshot.author_registration
    # Exact M1 registration_digest ABI; no DB helper is imported or executed here.
    payload = json.dumps(
        registration.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return (
        _digest(payload.encode())
        == snapshot.author_registration_sha256
        == target.work_snapshot_sha256
        and snapshot.author_binding == target.author
        and registration.work.company_id == target.company_id
        and registration.work.task_id == target.author.task_id
        and registration.work.trace_id == target.author.trace_id
        and registration.work.acceptance == target.criterion_ids
        and registration.run_id == target.author.run_id
        and registration.workflow_name == target.author.workflow_name
        and registration.workflow_version == target.author.workflow_version
        and registration.model_profile == target.author.model_profile
        and registration.model_registry_version == target.author.model_registry_version
    )


def check_internal_report(command: ReportCheckInput) -> ReportCheckResult:
    """Check one exact artifact against all registered criteria, never publish acceptance.

    Snapshot authenticity, current membership/ACL/fence and protection of the result
    remain the real publication boundary's responsibility. Distinct verifier UUIDs
    and even a passing result from this pure function establish no such authority.
    """
    early = _preflight(command)
    if early is not None:
        return early
    assert command.output_utf8 is not None
    try:
        report = _bounded_json(command.output_utf8)
    except (ValueError, UnicodeError, RecursionError, ValidationError):
        return _failure(command, "reject", "invalid_report_json_or_schema")
    if report.company_id != command.company_id:
        return _failure(command, "reject", "report_company_mismatch")
    outcomes = (
        _row("report.schema.v1", "pass", "bounded_report_schema_matches"),
        _citation_result(command, report),
        _time_result(command, report),
        _basis_result(command, report),
        *_operating_results(command, report),
    )
    by_id = {row.criterion_id: row for row in outcomes}
    return _result(command, tuple(by_id[cid] for cid in command.target.criterion_ids))
