"""Complete private engineering bytes retain first READ metadata and full-reference integrity."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import validate_utf8
from nexus.company.brain.scope_support import BrainDeniedError, brain_transaction
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import (
    QualifiedFreshness,
    RegisteredSourceFreshness,
    require_qualified_time,
)
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl

MAX_BODY_BYTES = 524288
BODY_READ_SECONDS = 30
_PAGE_BYTES = 16384
_MAX_PAGES = 33


@dataclass(frozen=True, slots=True)
class CompleteEngineeringBody:
    """Process-local material only; the genuine first slice is never a complete public DTO."""

    first: ArtifactSlice
    raw: bytes
    freshness: tuple[QualifiedFreshness, ...]

    def __post_init__(self) -> None:
        self.require_integrity()

    def require_integrity(self) -> None:
        first = ArtifactSlice.model_validate_json(self.first.model_dump_json())
        require_acceptance(
            first.source_state == "current"
            and first.span.start_byte == 0
            and type(self.raw) is bytes
            and len(self.raw) == first.artifact.byte_length <= MAX_BODY_BYTES
            and hashlib.sha256(self.raw).hexdigest() == first.artifact.sha256
            and first.text.encode() == self.raw[: first.span.end_byte]
        )
        validate_utf8(self.raw, max_bytes=MAX_BODY_BYTES)


def _metadata(value: ArtifactSlice) -> tuple[object, ...]:
    return (
        value.company_id,
        value.artifact,
        value.source_contributors,
        value.contributors,
        value.source_heads,
        value.data_classification,
        value.source_state,
    )


def _require_windows(first: ArtifactSlice, now: datetime) -> None:
    require_acceptance(now.utcoffset() is not None)
    require_acceptance(
        all(row.expires_at is None or row.expires_at > now for row in first.contributors)
        and all(
            row.availability == "available" and (row.fresh_until is None or row.fresh_until > now)
            for row in first.source_heads
        )
    )


def _composition(
    reader: BoundedArtifactReader, freshness: RegisteredSourceFreshness
) -> tuple[object, ...]:
    require_acceptance(reader.factory is freshness._factory)
    return reader.factory, reader.blobs, freshness._policies


def _require_composition(
    reader: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
    original: tuple[object, ...],
) -> None:
    require_acceptance(
        all(
            current is previous
            for current, previous in zip(_composition(reader, freshness), original, strict=True)
        )
    )


async def _page(
    reader: BoundedArtifactReader,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    reference: ArtifactRevisionRef,
    offset: int,
) -> ArtifactSlice:
    maximum = min(_PAGE_BYTES, reference.byte_length - offset)
    for retreat in range(4):
        try:
            value = await reader.bounded_artifact(
                scope,
                identity,
                reference.artifact_revision_id,
                start_byte=offset,
                max_bytes=maximum - retreat,
                include_history=False,
            )
        except BrainDeniedError as exc:
            # Only the existing strict UTF8 endpoint error permits a bounded same-offset retry.
            if (
                str(exc) != "Artifact byte boundary splits UTF8 content"
                or type(exc.__cause__) is not UnicodeDecodeError
                or retreat == min(3, maximum - 1)
            ):
                raise
            continue
        value = ArtifactSlice.model_validate_json(value.model_dump_json())
        require_acceptance(
            value.company_id == scope.company_id
            and value.artifact == reference
            and value.source_state == "current"
            and value.span.start_byte == offset
            and value.span.end_byte == offset + maximum - retreat
        )
        return value
    raise AssertionError("The bounded UTF8 attempts cannot fall through")


async def revalidate_complete_engineering_artifact_locked(
    reader: BoundedArtifactReader,
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    first: ArtifactSlice,
    now: datetime,
) -> None:
    """Keep original slice metadata and actual full stored tail checks in the same transaction."""
    first = ArtifactSlice.model_validate_json(first.model_dump_json())
    require_acceptance(
        session.in_transaction()
        and control.company_id == scope.company_id == first.company_id
        and first.span.start_byte == 0
        and first.source_state == "current"
        and first.artifact.byte_length <= MAX_BODY_BYTES
    )
    _require_windows(first, now)
    await reader.revalidate_artifact(
        session, control, scope, identity, first, await db_now(session)
    )
    await reader.revalidate_artifact_reference(
        session, control, scope, identity, first.artifact, await db_now(session)
    )
    _require_windows(first, await db_now(session))


async def load_complete_engineering_body(
    reader: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    reference: ArtifactRevisionRef,
) -> CompleteEngineeringBody:
    """Sequential <=33 pages/132 attempts; original first metadata is never refreshed away."""
    # This >50-line boundary keeps first policy capture, complete bytes and the final locked
    # slice/reference/window checks together. Public slices and permissions remain native.
    reference = ArtifactRevisionRef.model_validate_json(reference.model_dump_json())
    require_acceptance(
        reference.company_id == scope.company_id and reference.byte_length <= MAX_BODY_BYTES
    )
    original = _composition(reader, freshness)
    first: ArtifactSlice | None = None
    qualified: tuple[QualifiedFreshness, ...] = ()
    raw = bytearray()
    async with asyncio.timeout(BODY_READ_SECONDS):
        for _ in range(_MAX_PAGES):
            page = await _page(reader, scope, identity, reference, len(raw))
            _require_composition(reader, freshness, original)
            if first is None:
                first = page
                qualified = await freshness.prepare(scope, identity, (first,))
                _require_composition(reader, freshness, original)
            else:
                require_acceptance(_metadata(page) == _metadata(first))
            raw.extend(page.text.encode())
            require_acceptance(len(raw) <= reference.byte_length)
            if not page.has_more:
                break
        require_acceptance(first is not None and len(raw) == reference.byte_length)
        assert first is not None
        result = CompleteEngineeringBody(first, bytes(raw), qualified)
        async with brain_transaction(reader.factory, scope, identity) as (session, control, _):
            await revalidate_complete_engineering_artifact_locked(
                reader, session, control, scope, identity, first, await db_now(session)
            )
            await freshness.revalidate(session, scope, qualified, await db_now(session))
            final = await db_now(session)
            _require_composition(reader, freshness, original)
            _require_windows(first, final)
            require_qualified_time(qualified, final)
        return result
