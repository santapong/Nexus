"""Alternate-value source grammar checks; no original cases or golden answer lookups."""

from __future__ import annotations

from pydantic import JsonValue

from nexus.company.brain.base import SourceTime
from nexus.company.brain.context import ContextLimits
from nexus.company.brain.context_render import render_context
from nexus.company.brain.retrieval import MaterializedEvidence
from nexus.tests.brain_answer_fields import commitment_fields, report_fields
from nexus.tests.brain_source_fixtures import EvidenceFixture, Locator
from nexus.tests.unit.test_company_brain_context_render import SCOPE, authority, head, material


def _source(
    text: str,
    name: str,
    number: int,
    tier: str = "primary",
    event: str | None = None,
) -> tuple[MaterializedEvidence, EvidenceFixture]:
    item = material(text, identifier=number)
    record = item.record.model_copy(
        update={
            "source_event": SourceTime(
                precision="day" if event else "unknown",
                value=event,
                basis="independent alternate example",
            )
        }
    )
    item = MaterializedEvidence.model_validate_json(
        item.model_copy(
            update={"record": record, "authority_profile": f"operator.{tier}.v9"}
        ).model_dump_json()
    )
    return item, EvidenceFixture(
        case_id="alternate",
        company_id=item.company_id,
        evidence_id=record.evidence_id,
        artifact_id=record.artifact.artifact_id,
        source_revision_id=record.source.source_revision_id,
        source_alias=name,
        source_revision=record.source.revision,
        locator=Locator(kind="utf8_span", start_byte=0, end_byte=len(text.encode())),
        span_sha256=record.span_sha256,
    )


def _answer(
    examples: tuple[tuple[MaterializedEvidence, EvidenceFixture], ...],
    question: str,
) -> tuple[str, dict[str, JsonValue]] | None:
    items = tuple(row[0] for row in examples)
    context = render_context(
        SCOPE,
        authority(),
        ContextLimits(policy_version="alternate.v1"),
        items,
        tuple(head(row) for row in items),
        question=question,
    )
    result = report_fields(items, context, question, {row.evidence_id: row for _, row in examples})
    return result


def test_primary_mandate_keeps_unknown_event_even_when_summary_has_later_date() -> None:
    primary = _source("Owner mandate CharterZ remains supervised.", "CharterZ", 60)
    summary = _source("Later summary restates CharterZ.", "DigestY", 80, "summary", "2031-05-09")
    answer = _answer((summary, primary), "Which source establishes the mandate?")
    assert answer is not None and answer[1]["primary_source"] == "CharterZ"
    assert answer[1]["source_event"] is None and answer[1]["source_event_precision"] == "unknown"
    assert answer[1]["summary_event"] == "2031-05-09"


def test_arbitrary_customer_deadline_and_exact_event_date_are_extracted() -> None:
    source = _source(
        "Client Delta reports a deadline of 2032-09-17.", "Delta", 100, event="2032-08-04"
    )
    answer = _answer((source,), "When was the customer deadline learned?")
    assert answer is not None and answer[1]["deadline"] == "2032-09-17"
    assert answer[1]["source_event"] == "2032-08-04" and answer[1]["deadline_precision"] == "day"


def test_equal_authority_contradictions_keep_both_arbitrary_dates_unresolved() -> None:
    first = _source("Primary East: deadline 2034-06-11.", "East", 120)
    second = _source("Primary West: deadline 2034-06-19.", "West", 140)
    answer = _answer((second, first), "Which deadline is correct?")
    assert answer is not None and answer[0] == "unresolved_conflict"
    assert answer[1]["single_resolved_deadline"] is None
    assert answer[1]["deadline_candidates"] == [
        {"source": "East", "deadline": "2034-06-11"},
        {"source": "West", "deadline": "2034-06-19"},
    ]


def test_natural_language_unknown_deadline_is_not_filled_from_event_metadata() -> None:
    source = _source("Client Delta has not supplied a deadline.", "Delta", 160, event="2032-08-04")
    assert _answer((source,), "Which deadline is correct?") is None


def test_supersession_requires_explicit_affirmation_and_known_authorized_previous_source() -> None:
    old = _source("Owner decision Alpha retained.", "Alpha", 180, event="2030-01-02")
    new = _source(
        "Owner decision Beta explicitly supersedes Alpha.", "Beta", 200, event="2030-02-07"
    )
    answer = _answer((old, new), "Did the owner reverse the decision?")
    assert answer is not None and answer[1]["current_decision"] == "Beta"
    assert answer[1]["superseded_decision"] == "Alpha"
    assert _answer((new,), "Did the owner reverse the decision?") is None
    negated = _source(
        "Owner decision Beta does not explicitly supersedes Alpha.", "Beta", 200, event="2030-02-07"
    )
    assert _answer((old, negated), "Did the owner reverse the decision?") is None


def test_missing_or_invalid_calendar_date_is_not_promoted_into_deadline() -> None:
    source = _source("Client reports a deadline of 2033-99-77.", "DifferentClient", 220)
    assert _answer((source,), "Which deadline is correct?") is None
    assert (
        commitment_fields(
            "Commitment Launch is due 2030-15-80.", "Backend", "blocked", "owner_input"
        )
        is None
    )


def test_arbitrary_readiness_references_need_both_authorized_reports_and_remain_unspecified() -> (
    None
):
    source = _source(
        "Assessment AuditA cites test receipt ProofG and product source revision RevZ. "
        "The outcome was not supplied.",
        "AuditA",
        240,
        "summary",
    )
    receipt = _source("Receipt ProofG outcome not supplied.", "ProofG", 260, "synthetic_journal")
    revision = _source("Product revision RevZ exists.", "RevZ", 280)
    answer = _answer((source, receipt, revision), "What supports readiness?")
    assert answer is not None and answer[1]["supporting_references"] == ["ProofG", "RevZ"]
    assert answer[1]["readiness_pass"] is None
    assert _answer((source, receipt), "What supports readiness?") is None


def test_commitment_due_date_is_separate_from_arbitrary_blocked_work() -> None:
    answer = commitment_fields(
        "Customer commitment ShipZ is due 2036-02-19.", "IntegrateY", "blocked", "owner_input"
    )
    assert answer is not None and answer[1]["commitment"] == "ShipZ"
    assert answer[1]["commitment_due_date"] == "2036-02-19" and answer[1]["work"] == "IntegrateY"
    assert (
        answer[1]["work_state"] == "blocked" and answer[1]["blocking_dependency"] == "owner_input"
    )


def test_rejected_deadline_is_not_reported_as_an_agreed_deadline() -> None:
    source = _source(
        "Client Delta rejects a deadline of 2034-06-11; no deadline has been agreed.",
        "DeltaRejected",
        600,
    )
    result = _answer((source,), "Which deadline is correct?")
    assert result is None or result[0] != "answered"


def test_undecided_supersession_does_not_become_an_explicit_resolution() -> None:
    old = _source("Owner decision Alpha retained.", "Alpha", 620, event="2030-01-02")
    uncertain = _source(
        "Whether owner decision Beta explicitly supersedes Alpha remains undecided.",
        "Beta",
        640,
        event="2030-02-07",
    )
    result = _answer((old, uncertain), "Did the owner reverse the decision?")
    assert result is None or result[1].get("explicit_supersession") is not True


def test_conflicting_dates_in_one_primary_source_are_not_collapsed_to_first_match() -> None:
    source = _source(
        "Primary meeting report: deadline 2034-06-11. "
        "The same primary meeting report also states deadline 2034-06-19. "
        "These statements remain unresolved.",
        "Meeting",
        660,
    )
    result = _answer((source,), "Which deadline is correct?")
    assert result is None or (
        result[0] == "unresolved_conflict" and result[1].get("single_resolved_deadline") is None
    )


def test_event_date_does_not_fill_unknown_deadline() -> None:
    source = _source(
        "On 2034-06-11, Client Delta said the deadline remains unknown.",
        "DeltaUnknown",
        680,
    )
    assert _answer((source,), "Which deadline is correct?") is None


def test_deadline_date_must_be_bound_to_supported_affirmative_grammar() -> None:
    unrelated = _source("On 2037-02-08 we discussed a deadline.", "Discussion", 700)
    assert _answer((unrelated,), "Which deadline is correct?") is None
    supported = _source("Delivery deadline by 2039-03-12.", "Shipment", 720)
    result = _answer((supported,), "Which deadline is correct?")
    assert result is not None and result[1]["deadline"] == "2039-03-12"
    alternatives = _source("Deadline 2041-04-17 or 2041-04-28 remains possible.", "Options", 740)
    assert _answer((alternatives,), "Which deadline is correct?") is None
