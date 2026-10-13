"""Declared identity parsing preserves exact raw UTF8 evidence and trusted sections."""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from uuid import UUID

import pytest

from nexus.company.brain import parser as parser_module
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import SourceTime
from nexus.company.brain.parser import ParseRejectedError, parse_identity, parse_isolated
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import (
    ArtifactRevisionRecord,
    SourceRevisionRecord,
    UTF8Span,
)

COMPANY, SOURCE, ARTIFACT, REVISION, RESOURCE = (UUID(int=n) for n in range(1, 6))
NOW = datetime(2026, 10, 14, tzinfo=UTC)


def policy(**changes: object) -> SourcePolicy:
    return SourcePolicy.model_validate(
        {
            "source_symbol": "fixture.source.v1",
            "authority_profile": "fixture.reported.v1",
            "data_classification": "internal",
            "media_type": "text/plain",
            "parser_version": "utf8-identity-v1",
            "chunker_version": "utf8-sections-v1",
            "search_config": "simple",
            "freshness_seconds": None,
        }
        | changes
    )


def records(
    raw: bytes, media_type: str = "text/plain"
) -> tuple[ArtifactRevisionRecord, SourceRevisionRecord]:
    artifact = ArtifactRevisionRecord.model_validate(
        {
            "company_id": COMPANY,
            "artifact_id": ARTIFACT,
            "artifact_revision_id": REVISION,
            "revision": "source-r1",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_length": len(raw),
            "resource": ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            "media_type": media_type,
            "storage_symbol": "fixture.blobs.v1",
            "raw_text": raw.decode("utf-8"),
            "recorded_at": NOW,
        }
    )
    source = SourceRevisionRecord(
        company_id=COMPANY,
        source_id=SOURCE,
        source_revision_id=UUID(int=6),
        revision="source-r1",
        artifact=artifact,
        source_event=SourceTime(precision="day", value="2026-10-13", basis="source"),
        ingested_at=NOW,
        recorded_by=UUID(int=7),
    )
    return artifact, source


def test_identity_preserves_crlf_multibyte_unicode_and_exact_span_hashes() -> None:
    raw = "หัวข้อ\r\nCompany 🚀\r\nCafé café\n".encode()
    artifact, source = records(raw)
    parsed = parse_identity(source, artifact, policy())
    assert parsed.parse.canonical_text.encode() == raw
    assert parsed.parse.canonical_sha256 == hashlib.sha256(raw).hexdigest()
    assert b"".join(chunk.text.encode() for chunk in parsed.chunks) == raw
    assert len(parsed.evidence) == len(parsed.chunks)
    for chunk, evidence in zip(parsed.chunks, parsed.evidence, strict=True):
        span = raw[evidence.raw_span.start_byte : evidence.raw_span.end_byte]
        assert span == chunk.text.encode() and span.decode("utf-8") == chunk.text
        assert hashlib.sha256(span).hexdigest() == evidence.span_sha256
        assert evidence.raw_span == evidence.parsed_span


def test_identity_validates_json_without_whitespace_or_key_normalization() -> None:
    raw = b'{ "b": [2,1],\r\n "a": "\\u0e44" }\n'
    artifact, source = records(raw, "application/json")
    parsed = parse_identity(source, artifact, policy(media_type="application/json"))
    assert parsed.parse.canonical_text.encode() == raw
    assert parsed == parse_identity(source, artifact, policy(media_type="application/json"))


def test_malformed_json_is_a_bounded_failure_without_modifying_raw() -> None:
    raw = b'{"unfinished":'
    artifact, source = records(raw, "application/json")
    with pytest.raises(ParseRejectedError, match="invalid_json"):
        parse_identity(source, artifact, policy(media_type="application/json"))
    assert artifact.raw_text.encode() == raw


def test_trusted_section_boundaries_survive_chunking_and_do_not_split_utf8_codepoints() -> None:
    raw = ("หนึ่ง\n" + "two 🚀\n").encode()
    first = len("หนึ่ง\n".encode())
    artifact, source = records(raw)
    spans = (
        UTF8Span(start_byte=0, end_byte=first, section="section-1"),
        UTF8Span(start_byte=first, end_byte=len(raw), section="section-2"),
    )
    parsed = parse_identity(source, artifact, policy(), sections=spans)
    assert [x.raw_span.section for x in parsed.evidence] == ["section-1", "section-2"]
    assert [x.raw_span.start_byte for x in parsed.evidence] == [0, first]
    assert parsed.chunks[0].parsed_span.end_byte == first


@pytest.mark.parametrize("configuration", ["parser_version", "chunker_version"])
def test_unsupported_parser_configuration_fails_closed(
    configuration: str,
) -> None:
    artifact, source = records(b"raw source")
    with pytest.raises(ParseRejectedError, match="unsupported_recipe"):
        parse_identity(source, artifact, policy(**{configuration: "unsupported-v9"}))


def test_canonical_parse_byte_limit_does_not_publish_a_truncated_source() -> None:
    artifact, source = records(b"a" * 1_048_577)
    with pytest.raises(ParseRejectedError, match="parsed_too_large"):
        parse_identity(source, artifact, policy())


def slow_process(
    connection: Connection,
    source: SourceRevisionRecord,
    artifact: ArtifactRevisionRecord,
    configured: SourcePolicy,
    sections: tuple[UTF8Span, ...],
) -> None:
    """Deliberately block only an isolated fixture child, never the application event loop."""
    time.sleep(10)
    connection.close()


async def test_parser_timeout_terminates_isolated_process_and_returns_fixed_quarantine_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, source = records(b"bounded source")
    monkeypatch.setattr(parser_module, "_parse_child", slow_process)
    started = time.monotonic()
    with pytest.raises(ParseRejectedError, match="parse_timeout"):
        await parse_isolated(source, artifact, policy(parse_timeout_seconds=1))
    assert time.monotonic() - started < 4


def test_large_multibyte_sections_split_with_exact_contiguous_utf8_spans() -> None:
    raw = ("ไทย 🚀\r\n" * 3000).encode()
    artifact, source = records(raw)
    parsed = parse_identity(source, artifact, policy())
    assert b"".join(chunk.text.encode() for chunk in parsed.chunks) == raw
    assert all(len(chunk.text.encode()) <= 8192 for chunk in parsed.chunks)
    assert [chunk.parsed_span.start_byte for chunk in parsed.chunks[1:]] == [
        chunk.parsed_span.end_byte for chunk in parsed.chunks[:-1]
    ]
