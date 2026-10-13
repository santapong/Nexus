"""Bounded raw-byte integrity helpers; no cached parse text substitutes for source bytes."""

from __future__ import annotations

import hashlib

from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.sources import ArtifactRevisionRecord, ArtifactRevisionRef, EvidenceRecord


def raw_span_text(record: EvidenceRecord, artifact: ArtifactRevisionRecord, raw: bytes) -> str:
    """Check actual full artifact then exact span, including UTF8 codepoint boundaries."""
    record = EvidenceRecord.model_validate_json(record.model_dump_json())
    artifact = ArtifactRevisionRecord.model_validate_json(artifact.model_dump_json())
    stored = ArtifactRevisionRef.model_validate_json(
        artifact.model_dump_json(
            exclude={
                "resource",
                "media_type",
                "storage_symbol",
                "raw_text",
                "recorded_at",
                "derivation_id",
            }
        )
    )
    span = record.raw_span
    if (
        record.artifact != stored
        or raw != artifact.raw_text.encode()
        or len(raw) != artifact.byte_length
        or hashlib.sha256(raw).hexdigest() != artifact.sha256
        or span.end_byte > len(raw)
    ):
        raise BrainDeniedError("Brain evidence bytes are unavailable")
    selected = raw[span.start_byte : span.end_byte]
    if hashlib.sha256(selected).hexdigest() != record.span_sha256:
        raise BrainDeniedError("Brain evidence bytes are unavailable")
    try:
        return selected.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise BrainDeniedError("Brain evidence locator is unavailable") from exc
