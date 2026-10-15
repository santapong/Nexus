"""Typed slice delivery with mocked native READ/SQL; no actual authority or database proof."""

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder import engineering_bodies as module
from nexus.builder.engineering_bodies import CompleteEngineeringBody
from nexus.builder.engineering_contracts import (
    ENGINEERING_CRITERIA,
    EngineeringCheckResult,
    EngineeringCriterionResult,
)
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRef, SourceHead, SourceRevisionRef, UTF8Span
from nexus.company.management.acceptance_freshness import (
    QualifiedFreshness,
    RegisteredSourceFreshness,
)
from nexus.harness.journal_models import CompanyControl

NOW = datetime(2026, 10, 15, tzinfo=UTC)
COMPANY = UUID(int=1)


def described_check() -> EngineeringCheckResult:
    return EngineeringCheckResult(
        company_id=COMPANY,
        target_sha256="a" * 64,
        input_sha256="b" * 64,
        author_action_id=UUID(int=20),
        verifier_action_id=UUID(int=21),
        author_result_sha256="c" * 64,
        verifier_result_sha256="d" * 64,
        criteria=tuple(
            EngineeringCriterionResult(criterion_id=key, verdict="pass", reason="fixture")
            for key in ENGINEERING_CRITERIA
        ),
        verdict="pass",
    )


def described_body(raw: bytes, *, company: UUID = COMPANY) -> CompleteEngineeringBody:
    """Describe immutable bytes; this constructor is not a source-read permission stub."""
    reference = ArtifactRevisionRef(
        company_id=company,
        artifact_id=UUID(int=2),
        artifact_revision_id=UUID(int=3),
        revision="fixture.body.v1",
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
    )
    source = SourceRevisionRef(
        company_id=company, source_id=UUID(int=4), source_revision_id=UUID(int=5), revision="r1"
    )
    head = SourceHead(
        company_id=company,
        source_id=source.source_id,
        current=source,
        generation=1,
        observed_at=NOW,
        fresh_until=NOW + timedelta(seconds=60),
        availability="available",
    )
    policy = SourcePolicy(
        source_symbol="fixture.body",
        authority_profile="fixture.owner",
        data_classification="internal",
        origin_kind="derived",
        media_type="application/json",
        parser_version="v1",
        chunker_version="v1",
        search_config="simple",
        freshness_seconds=60,
    )
    end = min(16384, len(raw))
    while True:
        try:
            text = raw[:end].decode()
            break
        except UnicodeDecodeError:
            end -= 1
    first = ArtifactSlice(
        company_id=company,
        artifact=reference,
        span=UTF8Span(start_byte=0, end_byte=end),
        span_sha256=hashlib.sha256(raw[:end]).hexdigest(),
        text=text,
        source_contributors=(source,),
        contributors=(
            ResourceGeneration(
                company_id=company,
                resource_id=UUID(int=6),
                generation=1,
                expires_at=NOW + timedelta(seconds=30),
            ),
        ),
        source_heads=(head,),
        data_classification="internal",
        source_state="current",
        has_more=end < len(raw),
    )
    return CompleteEngineeringBody(
        first, raw, (QualifiedFreshness(source.source_id, policy, head.fresh_until, True),)
    )


@dataclass
class BodyCase:
    body: CompleteEngineeringBody
    reader: BoundedArtifactReader
    freshness: RegisteredSourceFreshness
    scope: BrainReadScope
    identity: VerifiedIdentity
    session: AsyncSession
    control: CompanyControl
    pages: AsyncMock
    prepare: AsyncMock
    revalidate: AsyncMock
    slice_check: AsyncMock
    reference_check: AsyncMock
    now: datetime = NOW

    async def page(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        key: UUID,
        *,
        start_byte: int,
        max_bytes: int,
        include_history: bool,
    ) -> ArtifactSlice:
        assert scope == self.scope and identity == self.identity
        assert key == self.body.first.artifact.artifact_revision_id and include_history is False
        assert 1 <= max_bytes <= 16384
        end = min(start_byte + max_bytes, len(self.body.raw))
        raw = self.body.raw[start_byte:end]
        try:
            text = raw.decode()
        except UnicodeDecodeError as exc:
            raise BrainDeniedError("Artifact byte boundary splits UTF8 content") from exc
        return self.body.first.model_copy(
            update={
                "span": UTF8Span(start_byte=start_byte, end_byte=end),
                "text": text,
                "span_sha256": hashlib.sha256(raw).hexdigest(),
                "has_more": end < len(self.body.raw),
            }
        )


def body_case(monkeypatch: pytest.MonkeyPatch, raw: bytes = b"x" * 20000) -> BodyCase:
    body = described_body(raw)
    factory = MagicMock(spec=async_sessionmaker)
    reader = MagicMock(spec=BoundedArtifactReader)
    reader.factory, reader.blobs = factory, object()
    freshness = MagicMock(spec=RegisteredSourceFreshness)
    freshness._factory, freshness._policies = factory, object()
    scope = BrainReadScope(
        company_id=body.first.company_id,
        workspace_id=UUID(int=10),
        principal_id=UUID(int=11),
        operation_id=UUID(int=12),
        trace_id=UUID(int=13),
    )
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    result = BodyCase(
        body,
        cast(BoundedArtifactReader, reader),
        cast(RegisteredSourceFreshness, freshness),
        scope,
        VerifiedIdentity(principal_id=scope.principal_id, workspace_id=scope.workspace_id),
        session,
        CompanyControl(company_id=scope.company_id, owner_id=scope.principal_id),
        AsyncMock(),
        AsyncMock(return_value=body.freshness),
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
    )
    result.pages.side_effect = result.page
    reader.bounded_artifact = result.pages
    reader.revalidate_artifact = result.slice_check
    reader.revalidate_artifact_reference = result.reference_check
    freshness.prepare, freshness.revalidate = result.prepare, result.revalidate

    @asynccontextmanager
    async def transaction(
        *args: object,
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        assert args == (factory, scope, result.identity)
        yield session, result.control, result.now

    async def clock(*args: object) -> datetime:
        return result.now

    monkeypatch.setattr(module, "brain_transaction", transaction)
    monkeypatch.setattr(module, "db_now", clock)
    return result


def without_expiry(case: BodyCase) -> None:
    first = case.body.first.model_copy(
        update={
            "contributors": tuple(
                row.model_copy(update={"expires_at": None}) for row in case.body.first.contributors
            ),
            "source_heads": tuple(
                row.model_copy(update={"fresh_until": None}) for row in case.body.first.source_heads
            ),
        }
    )
    original = case.body.freshness[0]
    qualified = QualifiedFreshness(
        original.source_id,
        original.policy.model_copy(update={"freshness_seconds": None}),
        None,
        True,
    )
    case.body = CompleteEngineeringBody(first, case.body.raw, (qualified,))
    case.prepare.return_value = case.body.freshness
    case.now += timedelta(hours=1)


async def load_body(case: BodyCase) -> CompleteEngineeringBody:
    return await module.load_complete_engineering_body(
        case.reader, case.freshness, case.scope, case.identity, case.body.first.artifact
    )
