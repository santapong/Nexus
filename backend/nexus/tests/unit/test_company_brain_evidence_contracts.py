"""Content hashes, raw locators and typed proposals cannot fabricate company truth."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import SourceTime
from nexus.company.brain.claims import ClaimCandidate
from nexus.company.brain.context import ContextSelection
from nexus.company.brain.events import OutboxEvent
from nexus.company.brain.ontology import EntityRevisionRef, WorkItemContent
from nexus.company.brain.relationships import RelationshipCandidate
from nexus.company.brain.sources import (
    ArtifactRevisionRecord,
    ArtifactRevisionRef,
    EvidenceRecord,
    EvidenceRef,
    SourceRevisionRef,
    UTF8Span,
)

COMPANY, SOURCE, REVISION, ARTIFACT = (UUID(int=i) for i in range(1, 5))
TEXT = "สวัสดี synthetic source\n"
RAW = TEXT.encode()
NOW = datetime(2026, 10, 14, tzinfo=UTC)


def artifact() -> ArtifactRevisionRecord:
    return ArtifactRevisionRecord(
        company_id=COMPANY,
        artifact_id=ARTIFACT,
        artifact_revision_id=UUID(int=5),
        revision="1",
        sha256=hashlib.sha256(RAW).hexdigest(),
        byte_length=len(RAW),
        resource=ResourceRef(company_id=COMPANY, resource_id=SOURCE),
        media_type="text/plain",
        storage_symbol="fixture-blob-v1",
        raw_text=TEXT,
        recorded_at=NOW,
    )


def evidence() -> EvidenceRecord:
    ref = ArtifactRevisionRef.model_validate(
        artifact().model_dump(
            include={
                "company_id",
                "artifact_id",
                "artifact_revision_id",
                "revision",
                "sha256",
                "byte_length",
            }
        )
    )
    return EvidenceRecord(
        company_id=COMPANY,
        evidence_id=UUID(int=6),
        source=SourceRevisionRef(
            company_id=COMPANY, source_id=SOURCE, source_revision_id=REVISION, revision="1"
        ),
        artifact=ref,
        raw_span=UTF8Span(start_byte=0, end_byte=len(RAW)),
        span_sha256=hashlib.sha256(RAW).hexdigest(),
        source_event=SourceTime(precision="month", value="2026-09", basis="source"),
        ingested_at=NOW,
    )


def test_utf8_byte_span_is_not_a_character_offset_or_imputed_timestamp() -> None:
    record = evidence()
    assert record.raw_span.end_byte > len(TEXT)
    assert record.source_event.precision == "month" and record.source_event.value == "2026-09"


@pytest.mark.parametrize(
    "update",
    [
        {"sha256": "0" * 64},
        {"byte_length": len(TEXT)},
        {"api_key": "forbidden"},
        {"endpoint_url": "https://unregistered.invalid"},
    ],
)
def test_artifact_metadata_must_bind_actual_bytes_and_exclude_credentials(
    update: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ArtifactRevisionRecord.model_validate(artifact().model_dump() | update)


@pytest.mark.parametrize(
    "update",
    [
        {"raw_span": UTF8Span(start_byte=0, end_byte=len(RAW) + 1)},
        {"parsed_span": UTF8Span(start_byte=0, end_byte=1)},
        {"chunk_id": UUID(int=99)},
    ],
)
def test_raw_and_parsed_locators_cannot_be_spliced(update: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EvidenceRecord.model_validate(evidence().model_dump() | update)


def test_same_named_artifact_from_another_company_fails_before_lookup() -> None:
    data = evidence().model_dump()
    data["artifact"]["company_id"] = UUID(int=99)
    with pytest.raises(ValidationError):
        EvidenceRecord.model_validate(data)


@pytest.mark.parametrize(
    "update",
    [
        {"kind": "verified_outcome"},
        {"status": "source_report"},
        {"verification_id": UUID(int=99)},
        {"completed": True},
    ],
)
def test_model_candidate_cannot_mint_verified_or_completed_state(update: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ClaimCandidate.model_validate(
            {
                "company_id": COMPANY,
                "claim_id": UUID(int=7),
                "kind": "hypothesis",
                "text": "Candidate",
                "source_event": SourceTime(precision="unknown", value=None, basis="not supplied"),
                "origin": "model",
            }
            | update
        )


@pytest.mark.parametrize(
    "update", [{"state": "completed"}, {"budget_usd": "100"}, {"role": "owner"}]
)
def test_work_ontology_fields_do_not_contain_execution_control(update: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        WorkItemContent.model_validate(
            {"kind": "WorkItem", "label": "test", "task_id": UUID(int=8)} | update
        )


def test_relationship_type_and_company_require_exact_ontology_endpoints() -> None:
    subject = EntityRevisionRef(
        company_id=COMPANY,
        entity_id=UUID(int=10),
        entity_revision_id=UUID(int=11),
        revision="1",
        kind="Customer",
    )
    target = EntityRevisionRef(
        company_id=COMPANY,
        entity_id=UUID(int=12),
        entity_revision_id=UUID(int=13),
        revision="1",
        kind="Goal",
    )
    with pytest.raises(ValidationError):
        RelationshipCandidate(
            company_id=COMPANY,
            relationship_id=UUID(int=14),
            predicate="supports_goal",
            subject=subject,
            object=target,
            origin="model",
        )


def test_context_request_cannot_supply_a_token_or_authority_budget() -> None:
    with pytest.raises(ValidationError):
        ContextSelection.model_validate(
            {"company_id": COMPANY, "max_tokens": 100000, "policy_version": "caller"}
        )


def test_outbox_is_id_only_and_requires_its_revision_binding() -> None:
    data = {
        "company_id": COMPANY,
        "event_id": UUID(int=15),
        "sequence": 1,
        "kind": "source_revised",
        "resource": ResourceRef(company_id=COMPANY, resource_id=SOURCE),
        "deduplication_key": "fixture-event-1",
        "operation_id": UUID(int=16),
        "trace_id": UUID(int=17),
        "recorded_at": NOW,
    }
    with pytest.raises(ValidationError):
        OutboxEvent.model_validate(data)
    with pytest.raises(ValidationError):
        OutboxEvent.model_validate(
            data | {"source_revision_id": REVISION, "body": "private source"}
        )
    assert (
        OutboxEvent.model_validate(data | {"source_revision_id": REVISION}).source_revision_id
        == REVISION
    )


def test_observation_candidate_without_source_support_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ClaimCandidate(
            company_id=COMPANY,
            claim_id=UUID(int=20),
            kind="observation",
            text="Fact",
            source_event=SourceTime(precision="unknown", value=None, basis="unknown"),
            origin="model",
        )
    hypothesis = ClaimCandidate(
        company_id=COMPANY,
        claim_id=UUID(int=20),
        kind="hypothesis",
        text="Possible",
        evidence=(EvidenceRef(company_id=COMPANY, evidence_id=UUID(int=6)),),
        source_event=SourceTime(precision="unknown", value=None, basis="unknown"),
        origin="model",
    )
    assert hypothesis.status == "proposed"
