"""Exact immutable fixture catalog for isolated PG seeding; no golden/authority projections."""

from __future__ import annotations

import hashlib
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import AwareDatetime

from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.tests.brain_source_fixtures import (
    FIXTURES,
    SOURCE_SHA256,
    FixtureRecord,
    SourcePack,
    frozen_sources,
)


def fixture_id(kind: str, key: UUID) -> UUID:
    """Versioned deterministic adapter identities; frozen source/evidence IDs remain exact."""
    return uuid5(NAMESPACE_URL, f"nexus.company.brain.fixture-adapter.v1:{kind}:{key}")


class CompanyFixture(FixtureRecord):
    active: Literal[True]
    alias: str
    company_id: UUID
    owner_id: UUID
    workspace_id: UUID


class PrincipalFixture(FixtureRecord):
    active: Literal[True]
    alias: str
    company_id: UUID
    principal_id: UUID
    role: Literal["member", "owner"]


class ArtifactFixture(FixtureRecord):
    artifact_id: UUID
    byte_length: int
    case_id: str
    company_id: UUID
    kind: Literal[
        "source",
        "summary",
        "embedding_derived_text",
        "chart_markup",
        "attachment",
        "workspace_file",
        "verification_evidence",
        "patch",
    ]
    mime_type: Literal["text/plain; charset=utf-8"]
    revision: str
    sha256: str
    source_revision_id: UUID | None = None
    storage_symbol: str
    text: str

    def reference(self) -> ArtifactRevisionRef:
        return ArtifactRevisionRef(
            company_id=self.company_id,
            artifact_id=self.artifact_id,
            artifact_revision_id=fixture_id("artifact-revision", self.artifact_id),
            revision=self.revision,
            sha256=self.sha256,
            byte_length=self.byte_length,
        )


class HeadFixture(FixtureRecord):
    as_of: AwareDatetime
    availability: Literal["available"]
    case_id: str
    company_id: UUID
    current_revision: str
    current_revision_id: UUID
    source_id: UUID


class AccessFixture(FixtureRecord):
    active: bool
    case_id: str
    company_id: UUID
    expires_at: AwareDatetime | None
    generation: int
    principal_id: UUID
    resource_id: UUID


class DerivationFixture(FixtureRecord):
    alias: str
    artifact_id: UUID
    case_id: str
    company_id: UUID
    contributing_source_revision_ids: tuple[UUID, ...]
    derivation_id: UUID
    kind: Literal["summary", "chart_markup", "embedding_derived_text"]
    read_policy: Literal["all_contributing_resources_must_be_currently_accessible"]
    recipe_version: str


class FixtureCatalog(FixtureRecord):
    companies: tuple[CompanyFixture, ...]
    principals: tuple[PrincipalFixture, ...]
    artifacts: tuple[ArtifactFixture, ...]
    source_heads: tuple[HeadFixture, ...]
    access_grants: tuple[AccessFixture, ...]
    derivations: tuple[DerivationFixture, ...]


def fixture_catalog() -> tuple[SourcePack, FixtureCatalog]:
    pack = frozen_sources()
    raw = (FIXTURES / "sources.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("Frozen source catalog changed")
    return pack, FixtureCatalog.model_validate_json(raw)
