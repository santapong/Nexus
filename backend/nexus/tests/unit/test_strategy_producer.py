"""Pure compiler boundaries; these fixtures confer no publication or strategic merit."""

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.management.canonical import canonical_json, canonical_sha256
from nexus.company.strategy.checker import check_strategy_material
from nexus.company.strategy.contracts import STRATEGY_CHECK_CRITERIA
from nexus.company.strategy.producer import (
    build_strategy_brief,
    prepare_strategy_artifact,
    strategy_input_bundle_bytes,
)
from nexus.company.strategy.producer_contracts import StrategyOriginalInputBundle
from nexus.execution.runtime_support import registration_digest
from nexus.tests.unit.strategy_producer_fixture import (
    bundle_ref,
    bundle_replay_process,
    large_strategy_output_case,
    producer_case,
)


def test_explicit_policy_compiles_original_quote_dates_and_rich_choices() -> None:
    snapshot, policy = producer_case()
    original = snapshot.model_dump_json()
    brief = build_strategy_brief(snapshot, policy)
    evidence = snapshot.sources[0].evidence
    quoted = snapshot.sources[0].raw_text.encode()[
        evidence.raw_span.start_byte : evidence.raw_span.end_byte
    ]
    assert brief.findings[0].quote.encode() == quoted
    assert brief.findings[0].source_event == evidence.source_event
    assert brief.findings[0].hypothesis == policy.finding_rules[0].hypothesis
    assert brief.candidates == policy.candidates
    assert brief.recommendation == policy.recommendation
    assert brief.unknowns == policy.unknowns
    assert brief.decision_request == policy.decision_request
    assert brief.deployed_state == "not_observed"
    assert snapshot.model_dump_json() == original
    rows = check_strategy_material(snapshot, brief)
    assert tuple(row.criterion_id for row in rows) == STRATEGY_CHECK_CRITERIA
    assert all(row.verdict == "pass" for row in rows)


def test_prepared_bytes_keep_original_manifest_and_separate_descriptive_bundle() -> None:
    snapshot, policy = producer_case()
    reference = bundle_ref(snapshot, policy)
    compiled = prepare_strategy_artifact(snapshot, policy, original_bundle=reference)
    assert compiled.prepared.inputs == snapshot.inputs
    assert compiled.prepared.input_manifest_sha256 == canonical_sha256(snapshot.inputs)
    assert compiled.brief.input_manifest_sha256 == compiled.prepared.input_manifest_sha256
    assert compiled.prepared.input_snapshot_sha256 == canonical_sha256(snapshot)
    assert compiled.prepared.raw_bytes == compiled.brief.model_dump_json().encode()
    assert (
        compiled.prepared.output_sha256 == hashlib.sha256(compiled.prepared.raw_bytes).hexdigest()
    )
    assert compiled.original_bundle == reference
    assert reference.artifact not in compiled.prepared.inputs.artifacts
    assert not hasattr(compiled, "acceptance_id")
    assert not hasattr(compiled, "strategic_merit")


def test_named_lossless_bundle_retains_original_registration_wire_identity() -> None:
    snapshot, policy = producer_case()
    raw = strategy_input_bundle_bytes(snapshot, policy)
    restored = StrategyOriginalInputBundle.model_validate_json(raw)
    assert restored.serialization == "strategy-input-bundle-json-v2"
    assert restored.snapshot == snapshot
    assert restored.policy == policy
    assert registration_digest(restored.snapshot.author_registration) == registration_digest(
        snapshot.author_registration
    )
    # Canonical hashes are identity digests, not the original lossless storage wire.
    normalized = StrategyOriginalInputBundle.model_validate_json(
        json.dumps(json.loads(canonical_json(restored))["payload"])
    )
    assert normalized.snapshot.author_registration == snapshot.author_registration
    assert registration_digest(normalized.snapshot.author_registration) != registration_digest(
        snapshot.author_registration
    )


@pytest.mark.parametrize("field", ["scope_sha256", "candidate_policy_sha256"])
def test_unmatched_server_policy_denies(field: str) -> None:
    snapshot, policy = producer_case()
    with pytest.raises(ValueError):
        build_strategy_brief(snapshot, policy.model_copy(update={field: "0" * 64}))


@pytest.mark.parametrize("field", ["input_snapshot_sha256", "producer_policy_sha256"])
def test_bundle_hash_binding_is_exact(field: str) -> None:
    snapshot, policy = producer_case()
    reference = bundle_ref(snapshot, policy).model_copy(update={field: "0" * 64})
    with pytest.raises(ValueError):
        prepare_strategy_artifact(snapshot, policy, original_bundle=reference)


@pytest.mark.parametrize("field,value", [("sha256", "0" * 64), ("byte_length", 1)])
def test_bundle_exact_wire_binding_denies_tampering(field: str, value: object) -> None:
    snapshot, policy = producer_case()
    reference = bundle_ref(snapshot, policy)
    changed = reference.model_copy(
        update={"artifact": reference.artifact.model_copy(update={field: value})}
    )
    with pytest.raises(ValueError):
        prepare_strategy_artifact(snapshot, policy, original_bundle=changed)


@pytest.mark.parametrize("field", ["artifact", "resource"])
def test_foreign_bundle_company_denies(field: str) -> None:
    snapshot, policy = producer_case()
    reference = bundle_ref(snapshot, policy)
    value = getattr(reference, field).model_copy(update={"company_id": UUID(int=999)})
    with pytest.raises(ValueError):
        prepare_strategy_artifact(
            snapshot, policy, original_bundle=reference.model_copy(update={field: value})
        )


@pytest.mark.parametrize("field", ["finding_id", "evidence_id"])
def test_duplicate_finding_selectors_deny(field: str) -> None:
    snapshot, policy = producer_case()
    first = policy.finding_rules[0]
    other = first.model_copy(update={"finding_id": "other", "evidence_id": UUID(int=888)})
    other = other.model_copy(update={field: getattr(first, field)})
    with pytest.raises(ValueError):
        build_strategy_brief(snapshot, policy.model_copy(update={"finding_rules": (first, other)}))


def test_missing_evidence_and_unbound_narrative_deny() -> None:
    snapshot, policy = producer_case()
    rule = policy.finding_rules[0].model_copy(update={"evidence_id": UUID(int=999)})
    with pytest.raises(ValueError):
        build_strategy_brief(snapshot, policy.model_copy(update={"finding_rules": (rule,)}))
    rationale = policy.recommendation.rationale.model_copy(update={"finding_ids": ("absent",)})
    recommendation = policy.recommendation.model_copy(update={"rationale": rationale})
    with pytest.raises(ValueError):
        build_strategy_brief(snapshot, policy.model_copy(update={"recommendation": recommendation}))


@pytest.mark.parametrize("field", ["quote", "source_event", "deployed_state", "economic_merit"])
def test_policy_cannot_override_evidence_or_claim_semantic_merit(field: str) -> None:
    snapshot, policy = producer_case()
    raw = policy.model_dump()
    raw[field] = "claimed"
    with pytest.raises(ValidationError):
        type(policy).model_validate(raw)
    assert build_strategy_brief(snapshot, policy).deployed_state == "not_observed"


@pytest.mark.parametrize(
    "field", ["model_requests", "tool_attempts", "rework_rounds", "plan_revisions"]
)
@pytest.mark.parametrize("value", [True, "1", 1.0])
def test_raw_nested_quota_invalidity_denies_before_serialization(field: str, value: object) -> None:
    snapshot, policy = producer_case()
    quota = snapshot.author_registration.quota.model_copy(update={field: value})
    registration = snapshot.author_registration.model_copy(update={"quota": quota})
    invalid = snapshot.model_copy(update={"author_registration": registration})
    with pytest.raises(ValueError):
        strategy_input_bundle_bytes(invalid, policy)


@pytest.mark.parametrize(
    "field,value", [("model_profile", "verification"), ("run_id", UUID(int=999))]
)
def test_original_registration_role_and_run_mismatch_deny(field: str, value: object) -> None:
    snapshot, policy = producer_case()
    registration = snapshot.author_registration.model_copy(update={field: value})
    invalid = snapshot.model_copy(update={"author_registration": registration})
    with pytest.raises(ValueError):
        build_strategy_brief(invalid, policy)


def test_generic_or_incomplete_strategy_criteria_cannot_compile() -> None:
    snapshot, policy = producer_case()
    for criteria in (("strategy.generic.v1",), STRATEGY_CHECK_CRITERIA[:-1]):
        work = snapshot.author_registration.work.model_copy(update={"acceptance": criteria})
        registration = snapshot.author_registration.model_copy(update={"work": work})
        scope = snapshot.scope.model_copy(
            update={"author_registration_sha256": registration_digest(registration)}
        )
        invalid = snapshot.model_copy(update={"author_registration": registration, "scope": scope})
        changed = policy.model_copy(update={"scope_sha256": canonical_sha256(scope)})
        with pytest.raises(ValueError):
            build_strategy_brief(invalid, changed)


@pytest.mark.parametrize("mutation", ["bytes", "span", "expired", "head", "manifest"])
def test_all_supplied_source_material_remains_checked(mutation: str) -> None:
    snapshot, policy = producer_case()
    source = snapshot.sources[0]
    if mutation == "bytes":
        source = source.model_copy(update={"raw_text": source.raw_text + "changed"})
    elif mutation == "span":
        evidence = source.evidence.model_copy(update={"span_sha256": "0" * 64})
        source = source.model_copy(update={"evidence": evidence})
    elif mutation == "expired":
        source = source.model_copy(
            update={
                "head": source.head.model_copy(
                    update={"fresh_until": snapshot.observed_at - timedelta(seconds=1)}
                )
            }
        )
    elif mutation == "head":
        source = source.model_copy(
            update={"head": source.head.model_copy(update={"availability": "unavailable"})}
        )
    else:
        snapshot = snapshot.model_copy(
            update={"inputs": snapshot.inputs.model_copy(update={"evidence": ()})}
        )
    with pytest.raises(ValueError):
        build_strategy_brief(snapshot.model_copy(update={"sources": (source,)}), policy)


@pytest.mark.parametrize("classification", ["public", "internal", "confidential", "restricted"])
def test_prepared_classification_never_downgrades_sources_or_policy(classification: str) -> None:
    snapshot, policy = producer_case()
    source = snapshot.sources[0]
    source = source.model_copy(
        update={
            "source_policy": source.source_policy.model_copy(
                update={"data_classification": classification}
            )
        }
    )
    snapshot = snapshot.model_copy(update={"sources": (source,)})
    compiled = prepare_strategy_artifact(
        snapshot, policy, original_bundle=bundle_ref(snapshot, policy)
    )
    assert compiled.prepared.data_classification == (
        "internal" if classification == "public" else classification
    )
    policy = policy.model_copy(update={"data_classification": "restricted"})
    assert (
        prepare_strategy_artifact(
            snapshot, policy, original_bundle=bundle_ref(snapshot, policy)
        ).prepared.data_classification
        == "restricted"
    )


def test_source_closure_reserves_three_slots_and_never_truncates() -> None:
    snapshot, policy = producer_case()
    artifact = snapshot.inputs.artifacts[0]
    extras = tuple(
        artifact.model_copy(
            update={"artifact_id": UUID(int=1000 + i), "artifact_revision_id": UUID(int=2000 + i)}
        )
        for i in range(30)
    )
    invalid = snapshot.model_copy(
        update={"inputs": snapshot.inputs.model_copy(update={"artifacts": (artifact, *extras)})}
    )
    with pytest.raises(ValueError):
        strategy_input_bundle_bytes(invalid, policy)
    assert len(invalid.inputs.artifacts) == 31


def test_bundle_storage_limit_does_not_truncate_original_source() -> None:
    snapshot, policy = producer_case()
    text = "x" * 2097152
    source = snapshot.sources[0]
    artifact = source.evidence.artifact.model_copy(
        update={"byte_length": len(text), "sha256": hashlib.sha256(text.encode()).hexdigest()}
    )
    evidence = source.evidence.model_copy(update={"artifact": artifact})
    source = source.model_copy(update={"evidence": evidence, "raw_text": text})
    invalid = snapshot.model_copy(
        update={
            "sources": (source,),
            "inputs": snapshot.inputs.model_copy(update={"artifacts": (artifact,)}),
        }
    )
    with pytest.raises(ValueError, match=r"bundle|Bundle"):
        strategy_input_bundle_bytes(invalid, policy)
    assert len(source.raw_text) == 2097152


def test_unselected_source_cannot_hide_invalid_original_bytes() -> None:
    snapshot, policy = producer_case()
    source = snapshot.sources[0]
    reference = source.evidence.source.model_copy(
        update={"source_id": UUID(int=400), "source_revision_id": UUID(int=401)}
    )
    artifact = source.evidence.artifact.model_copy(
        update={"artifact_id": UUID(int=402), "artifact_revision_id": UUID(int=403)}
    )
    evidence = source.evidence.model_copy(
        update={"evidence_id": UUID(int=404), "source": reference, "artifact": artifact}
    )
    extra = source.model_copy(
        update={
            "evidence": evidence,
            "head": source.head.model_copy(
                update={"source_id": reference.source_id, "current": reference}
            ),
            "raw_text": source.raw_text + "invalid unselected bytes",
        }
    )
    evidence_ref = snapshot.inputs.evidence[0].model_copy(
        update={"evidence_id": evidence.evidence_id}
    )
    inputs = snapshot.inputs.model_copy(
        update={
            "artifacts": (*snapshot.inputs.artifacts, artifact),
            "contributors": (*snapshot.inputs.contributors, reference),
            "evidence": (*snapshot.inputs.evidence, evidence_ref),
        }
    )
    invalid = snapshot.model_copy(update={"inputs": inputs, "sources": (source, extra)})
    with pytest.raises(ValueError, match="mechanical"):
        build_strategy_brief(invalid, policy)


def test_thirty_declared_input_artifacts_are_kept_without_truncation() -> None:
    snapshot, policy = producer_case()
    artifact = snapshot.inputs.artifacts[0]
    extras = tuple(
        artifact.model_copy(
            update={"artifact_id": UUID(int=1000 + i), "artifact_revision_id": UUID(int=2000 + i)}
        )
        for i in range(29)
    )
    inputs = snapshot.inputs.model_copy(update={"artifacts": (artifact, *extras)})
    snapshot = snapshot.model_copy(update={"inputs": inputs})
    compiled = prepare_strategy_artifact(
        snapshot, policy, original_bundle=bundle_ref(snapshot, policy)
    )
    assert len(compiled.prepared.inputs.artifacts) == 30
    assert compiled.prepared.inputs == inputs


def test_candidate_policy_and_narrative_basis_are_not_inferred() -> None:
    snapshot, policy = producer_case()
    with pytest.raises(ValueError, match="mechanical"):
        build_strategy_brief(
            snapshot, policy.model_copy(update={"candidates": tuple(reversed(policy.candidates))})
        )
    first = policy.candidates[0]
    bad = first.model_copy(update={"finding_ids": ("unproven",)})
    with pytest.raises(ValueError, match="mechanical"):
        build_strategy_brief(
            snapshot, policy.model_copy(update={"candidates": (bad, policy.candidates[1])})
        )


def test_original_bundle_ref_cannot_select_an_original_source_as_itself() -> None:
    snapshot, policy = producer_case()
    reference = bundle_ref(snapshot, policy)
    artifact = reference.artifact.model_copy(
        update={"artifact_id": snapshot.inputs.artifacts[0].artifact_id}
    )
    with pytest.raises(ValueError, match="bundle"):
        prepare_strategy_artifact(
            snapshot, policy, original_bundle=reference.model_copy(update={"artifact": artifact})
        )


def test_brief_output_byte_bound_is_checked_before_preparation() -> None:
    snapshot, policy = large_strategy_output_case()
    assert len(strategy_input_bundle_bytes(snapshot, policy)) < 2097152
    with pytest.raises(ValueError, match=r"output.*byte bound"):
        build_strategy_brief(snapshot, policy)


def test_original_bundle_replays_across_hash_seeds_without_wire_or_registration_change(
    tmp_path: Path,
) -> None:
    original = bundle_replay_process(tmp_path, "write", "0")
    assert original.returncode == 0, original.stderr
    expected = json.loads(original.stdout)
    assert (
        json.loads((tmp_path / "wire.json").read_text())["serialization"]
        == "strategy-input-bundle-json-v2"
    )
    for seed in ("0", "1", "2", "3"):
        replay = bundle_replay_process(tmp_path, "read", seed)
        assert replay.returncode == 0, replay.stderr
        assert json.loads(replay.stdout) == expected
