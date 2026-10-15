"""Generated HTML media/byte and pure identity-parser contracts; no ingestion or browser."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

import pytest

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import SourceTime
from nexus.company.brain.parser import ParseRejectedError, parse_identity
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRecord, SourceRevisionRecord
from nexus.tests.unit.cycle_deliverable_fixture import deliverable_case

COMPANY = UUID(int=1)
NOW = datetime(2026, 10, 15, tzinfo=UTC)


def policy(**changes: object) -> SourcePolicy:
    return SourcePolicy.model_validate(
        {
            "source_symbol": "fixture.generated-html.v1",
            "authority_profile": "fixture.reported.v1",
            "data_classification": "internal",
            "origin_kind": "derived",
            "media_type": "text/html",
            "parser_version": "utf8-identity-v1",
            "chunker_version": "utf8-sections-v1",
            "search_config": "simple",
            "freshness_seconds": None,
        }
        | changes
    )


def artifact(
    body: bytes = b"<!doctype html><p>Generated</p>", **changes: object
) -> ArtifactRevisionRecord:
    return ArtifactRevisionRecord.model_validate(
        {
            "company_id": COMPANY,
            "artifact_id": UUID(int=2),
            "artifact_revision_id": UUID(int=3),
            "revision": "generated-html-v1",
            "resource": ResourceRef(company_id=COMPANY, resource_id=UUID(int=4)),
            "sha256": hashlib.sha256(body).hexdigest(),
            "byte_length": len(body),
            "raw_text": body.decode(),
            "media_type": "text/html",
            "storage_symbol": "fixture.blobs.v1",
            "recorded_at": NOW,
            "derivation_id": UUID(int=5),
        }
        | changes
    )


def test_generated_html_is_truthfully_typed_as_derived_html() -> None:
    body = "<!doctype html><p>ไทย 🚀</p>\r\n".encode()
    configured, record = policy(), artifact(body)
    assert configured.media_type == record.media_type == "text/html"
    assert configured.origin_kind == "derived" and record.derivation_id == UUID(int=5)
    assert record.raw_text.encode() == body and record.byte_length == len(body)


def test_actual_generated_presentation_bytes_pass_pure_html_identity_contract() -> None:
    # This supplied-data producer fixture performs no actual engineering run or publication.
    case = deliverable_case("presentation")
    body = case.prepared.human_export
    ref = case.prepared.manifest.parts[1].artifact
    record = artifact(
        body, **ref.model_dump(), resource=case.basis.target, recorded_at=case.basis.observed_at
    )
    source = SourceRevisionRecord(
        company_id=ref.company_id,
        source_id=UUID(int=6),
        source_revision_id=UUID(int=7),
        revision="generated-html-v1",
        artifact=ref,
        source_event=SourceTime(
            precision="unknown", value=None, basis="synthetic producer fixture"
        ),
        ingested_at=case.basis.observed_at,
        recorded_by=UUID(int=8),
        derivation_id=record.derivation_id,
    )
    parsed = parse_identity(source, record, policy())
    assert body.startswith(b"<!doctype html>")
    assert parsed.parse.canonical_text.encode() == body
    assert parsed.parse.canonical_sha256 == record.sha256 == ref.sha256
    assert b"".join(row.text.encode() for row in parsed.chunks) == body
    for row in parsed.evidence:
        span = body[row.raw_span.start_byte : row.raw_span.end_byte]
        assert hashlib.sha256(span).hexdigest() == row.span_sha256
    with pytest.raises(ParseRejectedError, match="unsupported_media"):
        parse_identity(source, record, policy(media_type="text/plain", origin_kind="direct"))


def test_direct_html_policy_is_denied() -> None:
    with pytest.raises(ValueError):
        policy(origin_kind="direct")
    with pytest.raises(ValueError):
        SourcePolicy.model_validate(policy().model_dump(exclude={"origin_kind"}))


def test_html_artifact_requires_immutable_derivation_id() -> None:
    with pytest.raises(ValueError):
        artifact(derivation_id=None)


@pytest.mark.parametrize("media", ["text/plain", "text/markdown", "application/json"])
def test_existing_media_remain_available_without_html_derivation_rule(media: str) -> None:
    assert policy(media_type=media, origin_kind="direct").media_type == media
    assert (
        artifact(b'{"text":"unchanged"}', media_type=media, derivation_id=None).media_type == media
    )


@pytest.mark.parametrize(
    "media",
    ["image/svg+xml", "application/javascript", "text/javascript", "text/html; charset=utf-8"],
)
def test_other_media_remain_closed_even_for_derivatives(media: str) -> None:
    with pytest.raises(ValueError):
        policy(media_type=media)
    with pytest.raises(ValueError):
        artifact(media_type=media)


@pytest.mark.parametrize("change", ["hash", "length", "nul", "utf8_byte_cap"])
def test_html_preserves_exact_hash_length_nul_and_utf8_byte_bounds(change: str) -> None:
    body = "<p>ไทย</p>".encode()
    changes: dict[str, object] = {}
    if change == "hash":
        changes["sha256"] = "0" * 64
    elif change == "length":
        changes["byte_length"] = len(body) - 1
    elif change == "nul":
        body += b"\x00"
    else:
        body = ("ก" * 699051).encode()
    with pytest.raises(ValueError):
        artifact(body, **changes)
