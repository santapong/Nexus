"""Typed copied-value and safe-export data boundaries, independent of any native authority."""

import json
from uuid import uuid4

import pytest

from nexus.company.cycle_artifacts.checker import check_cycle_artifact
from nexus.company.cycle_artifacts.citations import quote_sources
from nexus.company.cycle_artifacts.engineering import compare_engineering_evidence
from nexus.company.cycle_artifacts.payloads import SupportDraft
from nexus.company.cycle_artifacts.production import prepare_presentation
from nexus.company.cycle_artifacts.renderers import support_markdown
from nexus.tests.unit.cycle_deliverable_fixture import deliverable_case


def test_copied_quote_text_must_still_hash_to_its_exact_original_span() -> None:
    case = deliverable_case()
    quote = case.basis.citations[0]
    changed = quote.model_copy(update={"quote": "x" + quote.quote[1:]})
    basis = case.basis.model_copy(update={"citations": (changed,)})
    with pytest.raises(ValueError):
        prepare_presentation(basis, case.action_id)


def test_public_markdown_renderer_denies_non_digest_interpolation_input() -> None:
    case = deliverable_case("support")
    body = SupportDraft.model_validate_json(case.prepared.typed_json)
    with pytest.raises(ValueError):
        support_markdown(body, "x\n<script>untrusted</script>")


@pytest.mark.parametrize("field", ["author_receipt", "verifier_receipt"])
def test_unknown_supplied_receipt_cannot_become_passing_engineering_basis(field: str) -> None:
    case = deliverable_case()
    receipt = getattr(case.evidence, field).model_copy(update={"outcome": "outcome_unknown"})
    with pytest.raises(ValueError):
        compare_engineering_evidence(case.evidence.model_copy(update={field: receipt}))


@pytest.mark.parametrize("field", ["author_utf8", "verifier_utf8", "check_utf8"])
def test_hash_reference_never_substitutes_for_exact_supplied_bytes(field: str) -> None:
    case = deliverable_case()
    with pytest.raises(ValueError):
        compare_engineering_evidence(case.evidence.model_copy(update={field: b"{}"}))


def test_changed_source_bytes_cannot_preserve_an_original_citation() -> None:
    case = deliverable_case()
    source = case.sources[0].model_copy(update={"raw_text": "changed source body"})
    with pytest.raises(ValueError):
        quote_sources((source,), case.basis.observed_at)


@pytest.mark.parametrize("change", ["source", "ttl"])
def test_copied_head_or_invented_policy_window_does_not_compile_as_fresh(change: str) -> None:
    from datetime import timedelta

    case = deliverable_case()
    source = case.sources[0]
    head = source.head.model_copy(
        update={"source_id": uuid4()}
        if change == "source"
        else {"fresh_until": source.head.observed_at + timedelta(days=999)}
    )
    with pytest.raises(ValueError):
        quote_sources((source.model_copy(update={"head": head}),), case.basis.observed_at)


@pytest.mark.parametrize("field", ["goal_id", "procedure_id"])
def test_engineering_projection_cannot_be_borrowed_by_another_goal_or_root(field: str) -> None:
    case = deliverable_case()
    engine = case.basis.engineering.model_copy(update={field: uuid4()})
    with pytest.raises(ValueError):
        prepare_presentation(case.basis.model_copy(update={"engineering": engine}), case.action_id)


def test_prior_placeholder_criteria_stay_incompatible_instead_of_silently_becoming_six_checks() -> (
    None
):
    case = deliverable_case()
    target = case.command().target.model_copy(
        update={"criterion_ids": ("cycle.presentation_check.v1",)}
    )
    result = check_cycle_artifact(case.command().model_copy(update={"target": target}))
    assert result.verdict == "inconclusive"


def test_json_with_customer_claim_stays_rejected_even_when_other_output_bytes_are_present() -> None:
    case = deliverable_case("support")
    body = json.loads(case.prepared.typed_json)
    body["customer_id"] = "invented customer"
    assert (
        check_cycle_artifact(
            case.command().model_copy(update={"typed_json": json.dumps(body).encode()})
        ).verdict
        == "reject"
    )
