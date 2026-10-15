"""Mechanical strategy descriptions cannot become economic merit, owner choice or acceptance."""

import json
from copy import deepcopy
from datetime import timedelta
from uuid import UUID

import pytest

from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import CriterionCheckResult
from nexus.company.strategy.checker import check_strategy_brief
from nexus.company.strategy.contracts import (
    STRATEGY_CHECK_CRITERIA,
    StrategyBrief,
    StrategyCheckPayload,
    StrategyCheckResult,
    StrategySelectionRef,
)
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.tests.unit.strategy_brief_fixture import strategy_case, with_raw


def test_rich_brief_checks_exact_sources_options_limits_without_economic_merit() -> None:
    item = strategy_case()
    result = check_strategy_brief(item.command)
    assert result.verdict == "pass"
    assert tuple(row.criterion_id for row in result.criteria) == STRATEGY_CHECK_CRITERIA
    assert result.strategic_merit == "not_evaluated"
    assert "mechanical_strategy_brief_only" in result.limitations
    assert "owner_choice_required" in result.limitations
    assert item.brief.candidates[0].expected_benefit.kind == "expectation"
    assert item.brief.findings[0].hypothesis is not None
    assert item.brief.findings[0].hypothesis.kind == "hypothesis"
    assert item.brief.deployed_state == "not_observed"


@pytest.mark.parametrize("field", ["approved", "completed", "owner_id", "economic_merit_pass"])
def test_brief_cannot_encode_authority_or_completion_flags(field: str) -> None:
    item = strategy_case()
    data = item.brief.model_dump() | {field: True}
    with pytest.raises(ValueError):
        StrategyBrief.model_validate(data)


@pytest.mark.parametrize(
    "kind",
    [
        "missing_tradeoffs",
        "empty_unknowns",
        "deployed_ready",
        "benefit_fact",
        "hypothesis_fact",
        "missing_request",
    ],
)
def test_rich_structure_and_claim_labels_are_required(kind: str) -> None:
    item = strategy_case()
    data = item.brief.model_dump(mode="json")
    if kind == "missing_tradeoffs":
        data["candidates"][0]["tradeoffs"] = []
    elif kind == "empty_unknowns":
        data["unknowns"] = []
    elif kind == "deployed_ready":
        data["deployed_state"] = "ready"
    elif kind == "benefit_fact":
        data["candidates"][0]["expected_benefit"]["kind"] = "verified_outcome"
    elif kind == "hypothesis_fact":
        data["findings"][0]["hypothesis"]["kind"] = "source_fact"
    else:
        del data["decision_request"]
    assert check_strategy_brief(with_raw(item, json.dumps(data).encode())).verdict == "reject"


@pytest.mark.parametrize(
    "kind",
    [
        "quote",
        "span_hash",
        "source_date",
        "invented_instant",
        "foreign_evidence",
        "duplicate_finding",
    ],
)
def test_exact_utf8_citations_dates_and_identities_are_recomputed(kind: str) -> None:
    item = strategy_case()
    data = item.brief.model_dump(mode="json")
    finding = data["findings"][0]
    if kind == "quote":
        finding["quote"] = "unsupported text"
    elif kind == "span_hash":
        finding["span_sha256"] = "f" * 64
    elif kind == "source_date":
        finding["source_event"]["value"] = "2026-09-02"
    elif kind == "invented_instant":
        finding["source_event"].update(precision="instant", value="2026-09-01T00:00:00Z")
    elif kind == "foreign_evidence":
        finding["evidence_id"] = str(UUID(int=999))
    else:
        data["findings"].append(deepcopy(finding))
    assert check_strategy_brief(with_raw(item, json.dumps(data).encode())).verdict != "pass"


@pytest.mark.parametrize(
    "kind",
    [
        "unknown_candidate",
        "wrong_patch",
        "wrong_tool",
        "extra_path",
        "recommend_foreign",
        "uncited_rationale",
        "missing_defer",
    ],
)
def test_recommendation_and_every_candidate_must_match_the_closed_policy(kind: str) -> None:
    item = strategy_case()
    data = item.brief.model_dump(mode="json")
    scope = data["candidates"][0]["scope"]
    if kind == "unknown_candidate":
        scope["candidate_id"] = "foreign"
    elif kind == "wrong_patch":
        scope["patch_sha256"] = "f" * 64
    elif kind == "wrong_tool":
        scope["tool"]["tool"] = "arbitrary.write.v1"
    elif kind == "extra_path":
        scope["write_paths"].append(".env")
    elif kind == "recommend_foreign":
        data["recommendation"]["candidate_id"] = "foreign"
    elif kind == "uncited_rationale":
        data["recommendation"]["rationale"]["finding_ids"] = ["foreign"]
    else:
        data["candidates"] = data["candidates"][:1]
    assert check_strategy_brief(with_raw(item, json.dumps(data).encode())).verdict == "reject"


@pytest.mark.parametrize(
    "kind",
    [
        "artifact_hash",
        "source_bytes",
        "registration_hash",
        "source_manifest",
        "scope",
        "input_manifest",
    ],
)
def test_snapshot_target_and_input_pins_cannot_be_spliced(kind: str) -> None:
    item = strategy_case()
    command = item.command
    snapshot = command.snapshot
    assert snapshot is not None
    if kind == "artifact_hash":
        command = command.model_copy(
            update={"output": command.output.model_copy(update={"sha256": "f" * 64})}
        )
    elif kind == "source_bytes":
        source = snapshot.sources[0].model_copy(update={"raw_text": "different source"})
        snapshot = snapshot.model_copy(update={"sources": (source,)})
        brief = item.brief.model_copy(update={"input_snapshot_sha256": canonical_sha256(snapshot)})
        command = with_raw(item, brief.model_dump_json().encode()).model_copy(
            update={"snapshot": snapshot}
        )
    elif kind == "registration_hash":
        command = command.model_copy(
            update={"target": command.target.model_copy(update={"work_snapshot_sha256": "f" * 64})}
        )
    else:
        data = item.brief.model_dump(mode="json")
        if kind == "source_manifest":
            data["source_manifest_sha256"] = "f" * 64
        elif kind == "input_manifest":
            data["input_manifest_sha256"] = "f" * 64
        else:
            data["scope"]["producing_plan"]["plan_revision_id"] = str(UUID(int=999))
        command = with_raw(item, json.dumps(data).encode())
    result = check_strategy_brief(command)
    assert result.verdict == "reject"
    if kind == "source_bytes":
        assert (
            next(
                row for row in result.criteria if row.criterion_id == "strategy.citations.v1"
            ).verdict
            == "reject"
        )


@pytest.mark.parametrize("kind", ["stale", "unavailable", "no_ttl_mismatch"])
def test_source_currentness_comes_from_explicit_supplied_policy_not_claimed_freshness(
    kind: str,
) -> None:
    item = strategy_case()
    snapshot = item.command.snapshot
    assert snapshot is not None
    source = snapshot.sources[0]
    if kind == "stale":
        assert source.head.fresh_until is not None
        snapshot = snapshot.model_copy(
            update={"observed_at": source.head.fresh_until + timedelta(seconds=1)}
        )
    elif kind == "unavailable":
        source = source.model_copy(
            update={"head": source.head.model_copy(update={"availability": "unavailable"})}
        )
    else:
        source = source.model_copy(
            update={
                "source_policy": source.source_policy.model_copy(update={"freshness_seconds": None})
            }
        )
    snapshot = snapshot.model_copy(update={"sources": (source,)})
    # Keep the brief's original snapshot identity consistent to nominate source-time semantics.
    brief = item.brief.model_copy(update={"input_snapshot_sha256": canonical_sha256(snapshot)})
    command = with_raw(item, brief.model_dump_json().encode()).model_copy(
        update={"snapshot": snapshot}
    )
    assert check_strategy_brief(command).verdict == "inconclusive"


@pytest.mark.parametrize(
    "criteria", [("cycle.strategy.v1",), (*STRATEGY_CHECK_CRITERIA, "strategy.economic-merit.v1")]
)
def test_legacy_generic_or_semantic_criteria_are_structurally_inconclusive(
    criteria: tuple[str, ...],
) -> None:
    item = strategy_case()
    command = item.command.model_copy(
        update={"target": item.command.target.model_copy(update={"criterion_ids": criteria})}
    )
    result = check_strategy_brief(command)
    assert result.verdict == "inconclusive"
    assert all(row.verdict == "inconclusive" for row in result.criteria)
    assert result.strategic_merit == "not_evaluated"


@pytest.mark.parametrize("missing", ["snapshot", "output_utf8"])
def test_missing_protected_input_is_inconclusive(missing: str) -> None:
    item = strategy_case()
    assert (
        check_strategy_brief(item.command.model_copy(update={missing: None})).verdict
        == "inconclusive"
    )


@pytest.mark.parametrize("raw", [b"not json", b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff"])
def test_malformed_json_data_rejects_without_success(raw: bytes) -> None:
    item = strategy_case()
    assert check_strategy_brief(with_raw(item, raw)).verdict == "reject"


@pytest.mark.parametrize("denial", [PermissionError, ExecutionDeniedError, BrainDeniedError])
def test_permission_failure_is_not_converted_to_a_quality_verdict(
    monkeypatch: pytest.MonkeyPatch,
    denial: type[Exception],
) -> None:
    from nexus.company.strategy import checker

    def denied(_: bytes) -> StrategyBrief:
        raise denial("nominated upstream authorization failure")

    monkeypatch.setattr(checker, "_decode", denied)
    with pytest.raises(denial):
        check_strategy_brief(strategy_case().command)


@pytest.mark.parametrize("raw", [False, True, 0.0, "0"])
def test_copied_raw_source_counts_are_not_normalized_before_validation(raw: object) -> None:
    item = strategy_case()
    snapshot = item.command.snapshot
    assert snapshot is not None
    source = snapshot.sources[0]
    changed = source.model_copy(
        update={
            "evidence": source.evidence.model_copy(
                update={"raw_span": source.evidence.raw_span.model_copy(update={"start_byte": raw})}
            )
        }
    )
    with pytest.raises(ValueError):
        check_strategy_brief(
            item.command.model_copy(
                update={"snapshot": snapshot.model_copy(update={"sources": (changed,)})}
            )
        )


def test_selection_ref_is_only_scoped_metadata_and_rejects_approval_flags() -> None:
    item = strategy_case()
    reference = StrategySelectionRef(
        company_id=item.command.company_id,
        brief=item.command.output,
        acceptance_id=UUID(int=999),
        candidate_id="csv-quantity",
        candidate_scope_sha256=canonical_sha256(item.brief.candidates[0].scope),
    )
    with pytest.raises(ValueError):
        StrategySelectionRef.model_validate(reference.model_dump() | {"approved": True})


@pytest.mark.parametrize("criterion", ["strategy.schema.v1", "strategy.economic-merit.v1"])
def test_checksum_consistent_partial_or_semantic_pass_result_is_not_a_valid_dto(
    criterion: str,
) -> None:
    result = check_strategy_brief(strategy_case().command)
    payload = StrategyCheckPayload.model_validate(
        result.model_dump(exclude={"result_sha256"})
        | {
            "criteria": (
                CriterionCheckResult(criterion_id=criterion, verdict="pass", reason="claimed_pass"),
            )
        }
    )
    with pytest.raises(ValueError):
        StrategyCheckResult(**payload.model_dump(), result_sha256=canonical_sha256(payload))
