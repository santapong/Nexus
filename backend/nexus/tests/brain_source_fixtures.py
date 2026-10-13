"""Frozen runtime fixture allowlist; golden answers/reviewer metadata are never source inputs."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, JsonValue, TypeAdapter

from nexus.company.brain.base import SourceTime
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.source_registry import SourceSnapshot
from nexus.company.brain.sources import SourceRegistration, UTF8Span
from nexus.tests.brain_projection_fixtures import Projection

SOURCE_SHA256 = "c3f6ded56d94d009e2f8246cf6f9f58cb2f23a40f4e783da33ce8729bfc670b2"
QUESTION_SHA256 = "c73731d1ac90f3a6fa34204fa5740444712938efea525ece834c1eae26e4d546"
FIXTURES = Path(__file__).parent / "fixtures" / "company_brain_v1"


class FixtureRecord(BaseModel):
    """Only explicit runtime fields are projected from hash-frozen synthetic metadata."""

    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)


class SourceFixture(FixtureRecord):
    alias: str
    case_id: str
    company_id: UUID
    source_id: UUID
    source_revision_id: UUID
    artifact_id: UUID
    evidence_id: UUID
    acl_resource_id: UUID
    external_key: str
    revision: str
    sha256: str
    source_symbol: Literal["fixture.synthetic.local"]
    source_event: SourceTime
    ingested_at: AwareDatetime
    author_id: UUID
    text: str
    authority: dict[str, JsonValue]


class Locator(FixtureRecord):
    kind: Literal["utf8_span"]
    start_byte: int
    end_byte: int
    section: str | None = None


class EvidenceFixture(FixtureRecord):
    case_id: str
    company_id: UUID
    evidence_id: UUID
    artifact_id: UUID
    source_revision_id: UUID
    source_alias: str
    source_revision: str
    locator: Locator
    span_sha256: str


class CaseSetup(FixtureRecord):
    case_id: str
    company_id: UUID
    workspace_id: UUID
    principal_id: UUID
    task_id: UUID
    trace_id: UUID
    operation_id: UUID
    registered_actor_id: UUID
    scope_kind: Literal["company_read", "work_read"]
    source_revision_ids: tuple[UUID, ...]
    state_projection_ids: tuple[UUID, ...]
    application_effects_enabled: Literal[False]


class SourcePack(FixtureRecord):
    fixture_version: Literal["company-brain-synthetic-v1"]
    scope: Literal["Synthetic acceptance data; no real company/customer facts or execution"]
    execution_status: Literal["not_executed"]
    original_question_pack_sha256: Literal[
        "c73731d1ac90f3a6fa34204fa5740444712938efea525ece834c1eae26e4d546"
    ]
    source_revisions: tuple[SourceFixture, ...]
    evidence: tuple[EvidenceFixture, ...]
    case_setup: tuple[CaseSetup, ...]
    state_projections: tuple[Projection, ...]


def frozen_sources(path: Path = FIXTURES / "sources.json") -> SourcePack:
    """Load only the hash-frozen runtime source file; never accept a golden/reviewer path."""
    if path.name != "sources.json":
        raise ValueError("Only the frozen runtime source input is permitted")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("Frozen Brain source bytes changed")
    pack = SourcePack.model_validate_json(raw)
    if len(pack.case_setup) != 30 or len({row.case_id for row in pack.case_setup}) != 30:
        raise ValueError("Every frozen case requires isolated setup")
    return pack


class FixtureSourceReader:
    """Named source bytes only; no filesystem/URL interpretation and no fixture authority."""

    def __init__(self, pack: SourcePack) -> None:
        self._pack = pack

    async def read(self, source: SourceRegistration, revision: str) -> SourceSnapshot:
        found = tuple(
            row
            for row in self._pack.source_revisions
            if (row.company_id, row.source_id, row.external_key, row.revision)
            == (source.company_id, source.source_id, source.external_key, revision)
        )
        if len(found) != 1 or source.source_symbol != "fixture.synthetic.local":
            raise BrainDeniedError("Frozen fixture source unavailable")
        row = found[0]
        raw = row.text.encode()
        if hashlib.sha256(raw).hexdigest() != row.sha256:
            raise BrainDeniedError("Frozen fixture source hash mismatch")
        sections = tuple(
            UTF8Span(
                start_byte=e.locator.start_byte,
                end_byte=e.locator.end_byte,
                section=e.locator.section,
            )
            for e in self._pack.evidence
            if e.source_revision_id == row.source_revision_id and e.locator.section is not None
        )
        return SourceSnapshot(
            company_id=row.company_id,
            source_id=row.source_id,
            source_symbol=row.source_symbol,
            external_key=row.external_key,
            revision=row.revision,
            raw_bytes=raw,
            source_event=row.source_event,
            source_author=str(row.author_id),
            sections=sections,
        )


class SealedManagementProvider:
    """Pure test projections expose no method that writes authority, budget or completion."""

    def __init__(self, pack: SourcePack) -> None:
        self._projections = pack.state_projections

    def for_case(self, case_id: str, company_id: UUID) -> tuple[Projection, ...]:
        return tuple(
            TypeAdapter(Projection).validate_json(row.model_dump_json())
            for row in self._projections
            if row.case_id == case_id and row.company_id == company_id
        )
