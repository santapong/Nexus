"""Pure bounded strategy checks; supplied descriptions confer no protected acceptance."""

import hashlib
import json
from datetime import timedelta

from pydantic import ValidationError

from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import CheckVerdict, CriterionCheckResult
from nexus.company.strategy.contracts import (
    STRATEGY_CHECK_CRITERIA,
    STRATEGY_CHECK_RECIPE,
    StrategyBrief,
    StrategyCheckInput,
    StrategyCheckPayload,
    StrategyCheckResult,
    StrategyCheckSnapshot,
    StrategyReasoning,
)


class _StrategyDataError(ValueError):
    """Malformed bounded JSON data only; authority and system failures are different classes."""


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _row(criterion: str, verdict: CheckVerdict, reason: str) -> CriterionCheckResult:
    return CriterionCheckResult(criterion_id=criterion, verdict=verdict, reason=reason)


def _result(
    command: StrategyCheckInput, criteria: tuple[CriterionCheckResult, ...]
) -> StrategyCheckResult:
    verdict: CheckVerdict = (
        "reject"
        if any(row.verdict == "reject" for row in criteria)
        else "inconclusive"
        if any(row.verdict == "inconclusive" for row in criteria)
        else "pass"
    )
    payload = StrategyCheckPayload(
        company_id=command.company_id,
        target_sha256=canonical_sha256(command.target),
        output_sha256=_digest(command.output_utf8) if command.output_utf8 is not None else None,
        input_snapshot_sha256=canonical_sha256(command.snapshot) if command.snapshot else None,
        verdict=verdict,
        criteria=criteria,
    )
    return StrategyCheckResult(**payload.model_dump(), result_sha256=canonical_sha256(payload))


def _failure(
    command: StrategyCheckInput, verdict: CheckVerdict, reason: str
) -> StrategyCheckResult:
    return _result(
        command, tuple(_row(cid, verdict, reason) for cid in command.target.criterion_ids)
    )


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _StrategyDataError("Duplicate strategy JSON key")
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise _StrategyDataError("Nonfinite strategy JSON constant")


def _decode(raw: bytes) -> StrategyBrief:
    value: object = json.loads(
        raw.decode("utf8"), object_pairs_hook=_unique, parse_constant=_constant
    )
    pending, nodes = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 12000 or depth > 20:
            raise _StrategyDataError("Strategy JSON exceeds structural bound")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return StrategyBrief.model_validate_json(raw)


def _snapshot_registration_matches(snapshot: StrategyCheckSnapshot) -> bool:
    scope, actual = snapshot.scope, snapshot.author_registration
    payload = json.dumps(
        actual.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    author = scope.author
    return (
        _digest(payload.encode()) == scope.author_registration_sha256
        and actual.work.company_id == snapshot.company_id
        and actual.work.goal_id == scope.goal.goal_id
        and (
            actual.work.task_id,
            actual.work.trace_id,
            actual.run_id,
            actual.workflow_name,
            actual.workflow_version,
            actual.model_profile,
            actual.model_registry_version,
        )
        == (
            author.task_id,
            author.trace_id,
            author.run_id,
            author.workflow_name,
            author.workflow_version,
            author.model_profile,
            author.model_registry_version,
        )
        and len(actual.work.acceptance) == len(STRATEGY_CHECK_CRITERIA)
        and set(actual.work.acceptance) == set(STRATEGY_CHECK_CRITERIA)
    )


def _registration_matches(command: StrategyCheckInput) -> bool:
    snapshot = command.snapshot
    assert snapshot is not None
    target, scope = command.target, snapshot.scope
    return (
        _snapshot_registration_matches(snapshot)
        and scope.author_registration_sha256 == target.work_snapshot_sha256
        and scope.author == target.author
        and scope.verifier == target.verifier
        and snapshot.author_registration.work.acceptance == target.criterion_ids
    )


def _preflight(command: StrategyCheckInput) -> StrategyCheckResult | None:
    criteria = command.target.criterion_ids
    if (
        command.target.check_recipe != STRATEGY_CHECK_RECIPE
        or set(criteria) != set(STRATEGY_CHECK_CRITERIA)
        or len(criteria) != len(STRATEGY_CHECK_CRITERIA)
    ):
        return _failure(command, "inconclusive", "unsupported_or_incomplete_strategy_criteria")
    if command.snapshot is None or command.output_utf8 is None:
        return _failure(command, "inconclusive", "protected_strategy_input_missing")
    if (
        not 0 < len(command.output_utf8) <= 262144
        or command.target.artifacts != (command.output,)
        or len(command.output_utf8) != command.output.byte_length
        or _digest(command.output_utf8) != command.output.sha256
        or not _registration_matches(command)
    ):
        return _failure(command, "reject", "exact_strategy_target_or_registration_mismatch")
    return None


def _sources(snapshot: StrategyCheckSnapshot, brief: StrategyBrief) -> CriterionCheckResult:
    criterion = "strategy.citations.v1"
    sources = {row.evidence.evidence_id: row for row in snapshot.sources}
    if (
        len(sources) != len(snapshot.sources)
        or len({row.finding_id for row in brief.findings}) != len(brief.findings)
        or len({row.evidence_id for row in brief.findings}) != len(brief.findings)
    ):
        return _row(criterion, "reject", "duplicate_strategy_evidence_or_finding")
    if {row.evidence_id for row in snapshot.inputs.evidence} != sources.keys():
        return _row(criterion, "reject", "strategy_evidence_manifest_mismatch")
    for source in snapshot.sources:
        evidence, raw = source.evidence, source.raw_text.encode()
        span = raw[evidence.raw_span.start_byte : evidence.raw_span.end_byte]
        if (
            len(raw) != evidence.artifact.byte_length
            or _digest(raw) != evidence.artifact.sha256
            or len(span) != evidence.raw_span.end_byte - evidence.raw_span.start_byte
            or _digest(span) != evidence.span_sha256
            or evidence.artifact not in snapshot.inputs.artifacts
            or evidence.source not in snapshot.inputs.contributors
        ):
            return _row(criterion, "reject", "strategy_original_source_bytes_or_manifest_mismatch")
    for finding in brief.findings:
        matched = sources.get(finding.evidence_id)
        if matched is None:
            return _row(criterion, "inconclusive", "strategy_citation_source_missing")
        evidence = matched.evidence
        raw = matched.raw_text.encode()[evidence.raw_span.start_byte : evidence.raw_span.end_byte]
        if (
            finding.source_revision_id,
            finding.artifact_revision_id,
            finding.span_sha256,
            finding.quote.encode(),
        ) != (
            evidence.source.source_revision_id,
            evidence.artifact.artifact_revision_id,
            evidence.span_sha256,
            raw,
        ):
            return _row(criterion, "reject", "strategy_quotation_or_scope_mismatch")
    return _row(criterion, "pass", "strategy_exact_utf8_citations_match")


def _times(snapshot: StrategyCheckSnapshot, brief: StrategyBrief) -> CriterionCheckResult:
    sources = {row.evidence.evidence_id: row for row in snapshot.sources}
    for finding in brief.findings:
        source = sources.get(finding.evidence_id)
        if source is None:
            return _row("strategy.source-time.v1", "inconclusive", "strategy_source_date_missing")
        if finding.source_event != source.evidence.source_event:
            return _row(
                "strategy.source-time.v1", "reject", "strategy_source_precision_or_date_mismatch"
            )
    for source in snapshot.sources:
        head, policy, evidence = source.head, source.source_policy, source.evidence
        deadline = (
            head.observed_at + timedelta(seconds=policy.freshness_seconds)
            if policy.freshness_seconds is not None
            else None
        )
        if (
            head.source_id != evidence.source.source_id
            or head.current != evidence.source
            or head.availability != "available"
            or head.observed_at > snapshot.observed_at
            or evidence.ingested_at > snapshot.observed_at
            or head.fresh_until != deadline
            or (deadline is not None and deadline <= snapshot.observed_at)
        ):
            return _row(
                "strategy.source-time.v1",
                "inconclusive",
                "strategy_source_not_current_under_supplied_policy",
            )
    return _row("strategy.source-time.v1", "pass", "strategy_exact_source_dates_and_policy_match")


def _candidates(snapshot: StrategyCheckSnapshot, brief: StrategyBrief) -> CriterionCheckResult:
    policy = snapshot.policy
    valid = (
        brief.repository == policy.repository
        and brief.source_manifest_sha256 == policy.source_manifest_sha256
        and tuple(row.scope for row in brief.candidates) == policy.candidates
        and any(row.sha256 == policy.source_manifest_sha256 for row in snapshot.inputs.artifacts)
    )
    return _row(
        "strategy.candidate-scope.v1",
        "pass" if valid else "reject",
        "strategy_candidate_policy_matches" if valid else "strategy_candidate_policy_mismatch",
    )


def _references(ids: tuple[str, ...], findings: set[str]) -> bool:
    return len(set(ids)) == len(ids) and bool(ids) and set(ids) <= findings


def _recommendation(brief: StrategyBrief) -> CriterionCheckResult:
    findings = {row.finding_id for row in brief.findings}
    descriptions: list[StrategyReasoning] = [brief.recommendation.rationale]
    descriptions.extend(row.hypothesis for row in brief.findings if row.hypothesis is not None)
    for candidate in brief.candidates:
        if not _references(candidate.finding_ids, findings):
            return _row(
                "strategy.recommendation-binding.v1", "reject", "strategy_candidate_basis_missing"
            )
        descriptions.append(candidate.expected_benefit)
        descriptions.extend(candidate.tradeoffs)
    valid = brief.recommendation.candidate_id in {
        row.scope.candidate_id for row in brief.candidates
    } and all(_references(row.finding_ids, findings) for row in descriptions)
    return _row(
        "strategy.recommendation-binding.v1",
        "pass" if valid else "reject",
        "strategy_recommendation_binding_matches"
        if valid
        else "strategy_recommendation_or_hypothesis_basis_mismatch",
    )


def check_strategy_brief(command: StrategyCheckInput) -> StrategyCheckResult:
    """Check supplied mechanical data; actual reader, owner and proof gates remain absent."""
    command = StrategyCheckInput.model_validate(command.model_dump(warnings=False))
    early = _preflight(command)
    if early is not None:
        return early
    assert command.snapshot is not None and command.output_utf8 is not None
    try:
        brief = _decode(command.output_utf8)
    except (
        json.JSONDecodeError,
        _StrategyDataError,
        ValidationError,
        UnicodeError,
        RecursionError,
    ):
        return _failure(command, "reject", "invalid_strategy_json_or_schema")
    rows = check_strategy_material(command.snapshot, brief)
    by_id = {row.criterion_id: row for row in rows}
    return _result(command, tuple(by_id[cid] for cid in command.target.criterion_ids))


def check_strategy_material(
    snapshot: StrategyCheckSnapshot, brief: StrategyBrief
) -> tuple[CriterionCheckResult, ...]:
    """Check six supplied-data properties without fabricating a receipt or target authority."""
    snapshot = StrategyCheckSnapshot.model_validate(snapshot.model_dump(warnings=False))
    brief = StrategyBrief.model_validate(brief.model_dump(warnings=False))
    if (
        brief.scope != snapshot.scope
        or brief.input_snapshot_sha256 != canonical_sha256(snapshot)
        or brief.input_manifest_sha256 != canonical_sha256(snapshot.inputs)
    ):
        return tuple(
            _row(cid, "reject", "strategy_scope_or_input_identity_mismatch")
            for cid in STRATEGY_CHECK_CRITERIA
        )
    if not _snapshot_registration_matches(snapshot):
        return tuple(
            _row(cid, "reject", "exact_strategy_target_or_registration_mismatch")
            for cid in STRATEGY_CHECK_CRITERIA
        )
    return (
        _row("strategy.schema.v1", "pass", "strategy_rich_schema_matches"),
        _sources(snapshot, brief),
        _times(snapshot, brief),
        _candidates(snapshot, brief),
        _recommendation(brief),
        _row(
            "strategy.unknowns.v1", "pass", "strategy_explicit_unknowns_and_owner_request_present"
        ),
    )
