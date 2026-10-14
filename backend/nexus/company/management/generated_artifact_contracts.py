"""Strict server-prepared artifact values; decoding confers no publication authority."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import validate_utf8
from nexus.company.brain.sources import ArtifactRevisionRef, EvidenceRef, SourceRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.base import (
    SHA256,
    ManagementContract,
    Name,
    Symbol,
    ValueContract,
    require_company,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.core.llm.company_registry import DataClassification
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.journal_models import CompanyControl

MAX_GENERATED_BYTES = 262_144
GeneratedTool = Literal["company.report.write.v1", "company.report.check.v1"]


class GeneratedArtifactInputs(ManagementContract):
    """Complete declared input manifest; actual native closure must still be resolved."""

    artifacts: tuple[ArtifactRevisionRef, ...] = Field(default=(), max_length=33)
    contributors: tuple[SourceRevisionRef, ...] = Field(default=(), max_length=32)
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=32)
    required_resource_ids: tuple[UUID, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def exact_inputs(self) -> Self:
        require_company(self.company_id, *self.artifacts, *self.contributors, *self.evidence)
        groups = (
            tuple(row.artifact_revision_id for row in self.artifacts),
            tuple(row.source_revision_id for row in self.contributors),
            tuple(row.evidence_id for row in self.evidence),
            self.required_resource_ids,
        )
        if any(len(set(values)) != len(values) for values in groups):
            raise ValueError("Generated input identities must be bounded and unique")
        if sum(row.byte_length for row in self.artifacts) > 8_650_752:
            raise ValueError("Generated input bytes exceed the complete preparation bound")
        return self


class GeneratedArtifactPayload(ManagementContract):
    """Server-produced exact bytes/input identity, with no audience/owner/verdict permit."""

    raw_bytes: bytes = Field(min_length=1, max_length=MAX_GENERATED_BYTES)
    output_sha256: SHA256
    input_snapshot_sha256: SHA256
    recipe_version: Symbol
    data_classification: DataClassification
    inputs: GeneratedArtifactInputs

    @model_validator(mode="after")
    def exact_bytes(self) -> Self:
        require_company(self.company_id, self.inputs)
        GeneratedArtifactInputs.model_validate_json(self.inputs.model_dump_json())
        validate_utf8(self.raw_bytes, max_bytes=MAX_GENERATED_BYTES)
        if hashlib.sha256(self.raw_bytes).hexdigest() != self.output_sha256:
            raise ValueError("Generated output hash differs from exact supported UTF8 bytes")
        return self

    @property
    def input_manifest_sha256(self) -> str:
        """Descriptive manifest checksum, separate from actual native input-snapshot hash."""
        return canonical_sha256(self.inputs)


class GeneratedArtifactActionParameters(ValueContract):
    """Fixed exact action pins; server validator resolves the native selector again."""

    recipe_version: Symbol
    output_sha256: SHA256
    input_snapshot_sha256: SHA256
    report_id: UUID | None = None
    verification_target_sha256: SHA256 | None = None
    author_action_id: UUID | None = None
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def one_native_selector(self) -> Self:
        if (self.report_id is None) == (self.verification_target_sha256 is None):
            raise ValueError("Generated action requires one exact report or check target")
        if (self.verification_target_sha256 is None) != (self.author_action_id is None):
            raise ValueError("Check target requires its exact native author action selector")
        if (
            len(set(self.evidence_ids)) != len(self.evidence_ids)
            or (self.report_id is not None and not self.evidence_ids)
            or (self.verification_target_sha256 is not None and self.evidence_ids)
        ):
            raise ValueError("Write requires exact unique evidence IDs; check inherits its target")
        return self


class GeneratedArtifactRule(ManagementContract):
    """Trusted target/policy/tool constructor configuration, absent from caller payloads."""

    tool: GeneratedTool
    tool_version: Literal["v1"] = "v1"
    resource_symbol: Name
    target: ResourceRef
    source_policy: Symbol
    recipe_version: Symbol

    @model_validator(mode="after")
    def scoped_target(self) -> Self:
        require_company(self.company_id, self.target)
        return self


class GeneratedArtifactValidator(Protocol):
    """Configured trusted native report/check recomputation, never an anonymous approval flag.

    Revalidation must use actual saved-report/VerificationSpec/loader inputs and
    compare bytes, complete input manifest and action pins. It performs bounded
    DB-only reads under the caller's CompanyControl transaction. A decoded DTO,
    claimed verifier ID or echo of its hashes cannot satisfy this implementation.
    """

    async def revalidate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        lease: ExecutionLease,
        actual_action: ActionProposal,
        prepared: GeneratedArtifactPayload,
        now: datetime,
    ) -> None: ...
