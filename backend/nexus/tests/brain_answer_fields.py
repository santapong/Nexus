"""Generic authorized report fields, exact provenance and explicit conflict/history semantics."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import JsonValue

from nexus.company.brain.context import AssembledContext
from nexus.company.brain.retrieval import MaterializedEvidence
from nexus.tests.brain_source_fixtures import EvidenceFixture

DATE = r"\d{4}-\d{2}-\d{2}"


def _uncertain(text: str) -> bool:
    return (
        re.search(
            r"\b(?:rejects?|rejected|whether|undecided|unconfirmed|tentative|conditional|"
            r"proposed|may|might|if|or|unknown|uncertain)\b|\b(?:no|not)\b",
            text,
            re.IGNORECASE,
        )
        is not None
    )


def _deadline_values(text: str) -> tuple[str, ...]:
    if _uncertain(text):
        return ()
    values: list[str] = []
    pattern = r"\bdeadline(?:\s+(?:of|is|by|equals|was|set for))?\s*(?:=|:)?\s*(" + DATE + r")"
    for value in re.findall(pattern, text, re.IGNORECASE):
        try:
            date.fromisoformat(value)
        except ValueError:
            continue
        if value not in values:
            values.append(value)
    return tuple(values)


def alias(item: MaterializedEvidence, aliases: Mapping[UUID, EvidenceFixture]) -> str:
    return aliases[item.record.evidence_id].source_alias


def _primary(items: tuple[MaterializedEvidence, ...]) -> MaterializedEvidence | None:
    candidates = tuple(row for row in items if ".primary." in row.authority_profile)
    return candidates[0] if len(candidates) == 1 else None


def _date(pattern: str, text: str) -> str | None:
    found = re.search(pattern, text, flags=re.IGNORECASE)
    if found is None:
        return None
    try:
        date.fromisoformat(found.group(1))
    except ValueError:
        return None
    return found.group(1)


def metadata_fields(item: MaterializedEvidence) -> dict[str, JsonValue]:
    return {
        "source_event": item.record.source_event.value,
        "source_event_precision": item.record.source_event.precision,
        "ingested_at": item.record.ingested_at.astimezone(ZoneInfo("Asia/Bangkok")).isoformat(),
    }


def report_fields(
    items: tuple[MaterializedEvidence, ...],
    context: AssembledContext,
    question: str,
    aliases: Mapping[UUID, EvidenceFixture],
) -> tuple[str, dict[str, JsonValue]] | None:
    text, query = "\n".join(row.text for row in items), question.lower()
    primary = _primary(items)
    if "omitted" in query and context.manifest.omissions:
        return _omissions(context)
    if "mandate" in query and primary is not None and "mandate" in primary.text.lower():
        facts = metadata_fields(primary)
        facts["primary_source"] = alias(primary, aliases)
        summaries = tuple(row for row in items if ".summary." in row.authority_profile)
        if len(summaries) == 1:
            facts["summary_event"] = summaries[0].record.source_event.value
        return "answered", facts
    if "readiness" in query and "not supplied" in text.lower():
        references = re.search(r"cites test receipt (\w+) and .*?source revision (\w+)", text)
        if references and set(references.groups()) <= {alias(row, aliases) for row in items}:
            return "answered", {
                "supporting_references": list(references.groups()),
                "receipt_result": "unspecified",
                "readiness_pass": None,
            }
    if "ingestion" in query and primary is not None:
        return _authority_event(primary, items, aliases)
    if "deadline" in query:
        return _deadlines(items, aliases)
    if "decision" in query:
        return _supersession(items, aliases)
    if "originate" in query or "provenance" in query:
        return _provenance(items, aliases)
    return None


def _deadlines(
    items: tuple[MaterializedEvidence, ...],
    aliases: Mapping[UUID, EvidenceFixture],
) -> tuple[str, dict[str, JsonValue]] | None:
    values = tuple(
        (row, value)
        for row in items
        if ".primary." in row.authority_profile
        for value in _deadline_values(row.text)
    )
    if len({value for _, value in values}) > 1:
        choices: list[JsonValue] = [
            {"source": alias(row, aliases), "deadline": value}
            for row, value in sorted(values, key=lambda pair: alias(pair[0], aliases))
        ]
        return "unresolved_conflict", {
            "conflict_state": "unresolved",
            "deadline_candidates": choices,
            "single_resolved_deadline": None,
        }
    if len(values) == 1:
        row, deadline = values[0]
        facts = metadata_fields(row)
        facts.update(
            deadline=deadline,
            deadline_precision="day",
            ingestion_date=row.record.ingested_at.astimezone(ZoneInfo("Asia/Bangkok"))
            .date()
            .isoformat(),
        )
        return "answered", facts
    return None


def _authority_event(
    primary: MaterializedEvidence,
    items: tuple[MaterializedEvidence, ...],
    aliases: Mapping[UUID, EvidenceFixture],
) -> tuple[str, dict[str, JsonValue]] | None:
    summaries = tuple(row for row in items if ".summary." in row.authority_profile)
    if len(summaries) != 1:
        return None
    summary = summaries[0]
    return "answered", {
        "selected_primary": alias(primary, aliases),
        "primary_event_date": primary.record.source_event.value,
        "summary_described_event_date": _date(r"event dated (" + DATE + r")", summary.text),
        "summary_ingestion_date": summary.record.ingested_at.astimezone(ZoneInfo("Asia/Bangkok"))
        .date()
        .isoformat(),
        "selection_basis": "source_authority_and_event_not_ingestion_order",
    }


def _supersession(
    items: tuple[MaterializedEvidence, ...],
    aliases: Mapping[UUID, EvidenceFixture],
) -> tuple[str, dict[str, JsonValue]] | None:
    statements = tuple(
        (row, re.search(r"explicitly supersedes (\w+)", row.text))
        for row in items
        if ".primary." in row.authority_profile
    )
    affirmative = tuple(
        (row, match) for row, match in statements if match is not None and not _uncertain(row.text)
    )
    if len(affirmative) != 1:
        return None
    current, match = affirmative[0]
    assert match is not None
    previous = next((row for row in items if alias(row, aliases) == match.group(1)), None)
    if (
        previous is None
        or current.record.source_event.precision != previous.record.source_event.precision
    ):
        return None
    return "answered", {
        "current_decision": alias(current, aliases),
        "current_decision_date": current.record.source_event.value,
        "superseded_decision": alias(previous, aliases),
        "superseded_decision_date": previous.record.source_event.value,
        "date_precision": current.record.source_event.precision,
        "explicit_supersession": True,
    }


def _provenance(
    items: tuple[MaterializedEvidence, ...],
    aliases: Mapping[UUID, EvidenceFixture],
) -> tuple[str, dict[str, JsonValue]] | None:
    summaries = tuple(row for row in items if ".summary." in row.authority_profile)
    if len(summaries) != 1:
        return None
    summary = summaries[0]
    roots = tuple(ref for ref in summary.source_contributors if ref != summary.record.source)
    primary = next(
        (row for row in items if len(roots) == 1 and row.record.source == roots[0]), None
    )
    if primary is None:
        return None
    return "answered", {
        "summary": alias(summary, aliases),
        "primary_source": alias(primary, aliases),
        "primary_revision": primary.record.source.revision,
    }


def _omissions(context: AssembledContext) -> tuple[str, dict[str, JsonValue]] | None:
    rows = context.manifest.inclusions
    artifacts = {row.handle.record.artifact.artifact_id for row in rows}
    if len(artifacts) != 1:
        return None
    included = list[JsonValue](
        sorted(
            {
                int(row.handle.record.raw_span.section)
                for row in rows
                if row.handle.record.raw_span.section
                and row.handle.record.raw_span.section.isdigit()
            }
        )
    )
    omitted = list[JsonValue](
        sorted(
            {
                int(row.section)
                for row in context.manifest.omissions
                if row.section and row.section.isdigit()
            }
        )
    )
    return "answered", {
        "included_sections": included,
        "omitted_sections": omitted,
        "bounded_followup": {
            "artifact_id": str(next(iter(artifacts))),
            "maximum_bytes": 1024,
            "requires_current_acl": True,
        },
    }


def commitment_fields(
    text: str,
    work: str,
    state: str,
    dependency: str,
) -> tuple[str, dict[str, JsonValue]] | None:
    commitment = re.search(r"commitment\s+(\w+)\s+is due\s+(" + DATE + r")", text, re.IGNORECASE)
    if commitment is None:
        return None
    due = _date(r"commitment\s+\w+\s+is due\s+(" + DATE + r")", text)
    if due is None:
        return None
    return "answered", {
        "commitment": commitment.group(1),
        "commitment_due_date": due,
        "date_precision": "day",
        "work": work,
        "work_state": state,
        "blocking_dependency": dependency,
    }
