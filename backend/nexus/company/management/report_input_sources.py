"""Bounded protected report/source selection; model claims cannot supply source bytes."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import AcceptanceDeniedError, require_acceptance
from nexus.company.management.check_contracts import (
    REPORT_CHECK_RECIPE,
    SourceQuoteClaim,
    StructuredInternalReport,
)

MAX_REPORT_BYTES = 262_144
MAX_SOURCE_BYTES = 8_388_608
MAX_ARTIFACT_BYTES = 2_097_152
PAGE_BYTES = 16_384


class ReportByteReader(Protocol):
    async def bounded_artifact(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        artifact_revision_id: UUID,
        *,
        start_byte: int,
        max_bytes: int,
        include_history: bool,
    ) -> ArtifactSlice: ...


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def report_request(
    target: VerificationSpec, output: ArtifactRevisionRef, raw: bytes
) -> tuple[StructuredInternalReport, tuple[UUID, ...]]:
    """Interpret only exact protected output bytes for the registered single-output recipe."""
    require_acceptance(
        target.check_recipe == REPORT_CHECK_RECIPE
        and target.artifacts == (output,)
        and output.company_id == target.company_id
        and 0 < len(raw) <= MAX_REPORT_BYTES
        and len(raw) == output.byte_length
        and hashlib.sha256(raw).hexdigest() == output.sha256
    )
    try:
        json.loads(raw, object_pairs_hook=_unique_object)
        report = StructuredInternalReport.model_validate_json(raw)
    except (ValueError, UnicodeError, ValidationError) as exc:
        raise AcceptanceDeniedError("Protected structured report is unavailable") from exc
    require_acceptance(report.company_id == target.company_id)
    ids = tuple(row.evidence_id for row in report.claims if isinstance(row, SourceQuoteClaim))
    require_acceptance(len(ids) <= 32 and len(set(ids)) == len(ids))
    return report, ids


async def protected_bytes(
    reader: ReportByteReader,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    reference: ArtifactRevisionRef,
    *,
    max_bytes: int,
) -> bytes:
    """Read complete UTF8 pages with unchanged provenance and full-reference integrity."""
    require_acceptance(
        reference.company_id == scope.company_id
        and 0 < reference.byte_length <= min(max_bytes, MAX_ARTIFACT_BYTES)
    )
    raw, previous, offset = bytearray(), None, 0
    # UTF8-aligned pages can contain up to three fewer bytes than their requested bound.
    for _ in range(129):
        page = await reader.bounded_artifact(
            scope,
            identity,
            reference.artifact_revision_id,
            start_byte=offset,
            max_bytes=PAGE_BYTES,
            include_history=False,
        )
        require_acceptance(page.artifact == reference and page.span.start_byte == offset)
        shape = page.model_dump(exclude={"span", "span_sha256", "text", "has_more"})
        require_acceptance(previous is None or previous == shape)
        previous = shape
        raw.extend(page.text.encode())
        offset = page.span.end_byte
        require_acceptance(offset == len(raw) and len(raw) <= reference.byte_length)
        if not page.has_more:
            break
    require_acceptance(
        len(raw) == reference.byte_length and hashlib.sha256(raw).hexdigest() == reference.sha256
    )
    return bytes(raw)
