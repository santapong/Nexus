"""Exact raw UTF8 artifact bytes cannot be replaced by cached parser text."""

import hashlib
from datetime import UTC, datetime
from uuid import UUID

import pytest

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.retrieval_support import raw_span_text
from nexus.company.brain.sources import ArtifactRevisionRecord, UTF8Span
from nexus.tests.unit.test_company_brain_context_render import COMPANY, material


def artifact(text: str) -> ArtifactRevisionRecord:
    item = material(text)
    return ArtifactRevisionRecord(
        **item.record.artifact.model_dump(),
        resource=ResourceRef(company_id=COMPANY, resource_id=UUID(int=25)),
        media_type="text/plain",
        storage_symbol="fixture.local",
        raw_text=text,
        recorded_at=datetime.now(UTC),
    )


def test_raw_exact_utf8_span_validates_full_artifact_and_span_hash() -> None:
    text = "ก evidence"
    item = material(text)
    assert raw_span_text(item.record, artifact(text), text.encode()) == text


@pytest.mark.parametrize("fault", ["bytes", "hash", "foreign", "boundary"])
def test_corrupt_foreign_or_split_codepoint_is_denied(fault: str) -> None:
    text = "กA"
    record, stored, raw = material(text).record, artifact(text), text.encode()
    if fault == "bytes":
        raw = b"other bytes"
    elif fault == "hash":
        record = record.model_copy(update={"span_sha256": "0" * 64})
    elif fault == "foreign":
        stored = stored.model_copy(update={"company_id": UUID(int=999)})
    else:
        record = record.model_copy(
            update={
                "raw_span": UTF8Span(start_byte=1, end_byte=3),
                "span_sha256": hashlib.sha256(raw[1:3]).hexdigest(),
            }
        )
    with pytest.raises(ValueError):
        raw_span_text(record, stored, raw)
