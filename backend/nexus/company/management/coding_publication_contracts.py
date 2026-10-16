"""Closed generated Brain data; no decoded origin, publication or reference grants authority."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Literal, Self
from uuid import UUID, uuid5

from pydantic import AwareDatetime, Field, model_validator

from nexus.builder.contracts import BuilderArtifact
from nexus.company.brain.base import SHA256, BrainContract, ValueContract
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import (
    ArtifactRevisionRef,
    IngestReceipt,
    SourceRegistration,
    SourceRevisionRef,
)
from nexus.company.contracts.base import USD
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_content import CodeChangeContent
from nexus.company.management.coding_prepared_contracts import CodingPreparedHeader
from nexus.core.llm.company_pricing import PriceCard, TokenUsage, reconcile_cost
from nexus.core.llm.company_registry import ApiFamily, Provider
from nexus.harness.journal_budget import billing_day

PublicationKind = Literal["model_origin", "code_patch"]
RECIPE = "nexus.coding.publication.v1"
ORIGIN_LIMIT, PATCH_LIMIT = 131_072, 32_768


def publication_identity(
    company: UUID, action: UUID, request_sha256: str, kind: PublicationKind, raw: bytes
) -> tuple[SourceRevisionRef, ArtifactRevisionRef, UUID]:
    """Names bind the original request; changed bytes conflict rather than mint another revision."""
    if kind not in {"model_origin", "code_patch"} or type(raw) is not bytes:
        raise ValueError("Unsupported coding publication data")
    if len(request_sha256) != 64 or any(c not in "0123456789abcdef" for c in request_sha256):
        raise ValueError("Coding publication needs the exact request hash")
    if not 0 < len(raw) <= (ORIGIN_LIMIT if kind == "model_origin" else PATCH_LIMIT):
        raise ValueError("Complete coding publication exceeds its byte bound")
    raw.decode("utf-8")
    source, artifact = (
        uuid5(action, f"coding-{kind}-source-v1"),
        uuid5(action, f"coding-{kind}-artifact-v1"),
    )
    revision = f"{RECIPE}:{request_sha256}"
    return (
        SourceRevisionRef(
            company_id=company,
            source_id=source,
            source_revision_id=uuid5(source, f"source-revision-v1:{revision}"),
            revision=revision,
        ),
        ArtifactRevisionRef(
            company_id=company,
            artifact_id=artifact,
            artifact_revision_id=uuid5(artifact, request_sha256),
            revision=revision,
            sha256=hashlib.sha256(raw).hexdigest(),
            byte_length=len(raw),
        ),
        uuid5(artifact, "derivation-v1"),
    )


class CodingPublicationRules(BrainContract):
    action_id: UUID
    origin: SourceRegistration
    patch: SourceRegistration
    origin_policy: SourcePolicy
    patch_policy: SourcePolicy
    readers: tuple[UUID, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def exact_registered_pair(self) -> Self:
        if (
            len(set(self.readers)) != len(self.readers)
            or self.origin.resource == self.patch.resource
            or self.origin_policy.data_classification != self.patch_policy.data_classification
        ):
            raise ValueError("Coding publication initial audience/targets differ")
        for kind, source, policy, media, maximum in (
            ("model_origin", self.origin, self.origin_policy, "application/json", ORIGIN_LIMIT),
            ("code_patch", self.patch, self.patch_policy, "text/plain", PATCH_LIMIT),
        ):
            if (
                (
                    source.company_id,
                    source.resource.company_id,
                    source.source_id,
                    source.source_symbol,
                    source.external_key,
                )
                != (
                    self.company_id,
                    self.company_id,
                    uuid5(self.action_id, f"coding-{kind}-source-v1"),
                    f"nexus.coding.{kind}.v1",
                    str(self.action_id),
                )
                or policy.source_symbol != source.source_symbol
                or policy.origin_kind != "derived"
                or policy.authority_profile != "coding.generated.v1"
                or policy.media_type != media
                or policy.allowed_external_keys != frozenset({str(self.action_id)})
                or policy.max_bytes != maximum
                or policy.freshness_seconds is not None
                or (policy.parser_version, policy.chunker_version)
                != ("utf8-identity-v1", "utf8-sections-v1")
            ):
                raise ValueError(
                    "Coding publication source/policy is not the closed configured pair"
                )
        return self


class CodingModelOrigin(ValueContract):
    """Actual publisher-generated result data; never a caller-posted native attestation."""

    format: Literal["nexus.coding.model-origin.v1"] = "nexus.coding.model-origin.v1"
    header: CodingPreparedHeader
    native_proposal_sha256: SHA256
    intent_fence: int = Field(gt=0, strict=True)
    intent_created_at: AwareDatetime
    receipt_id: UUID
    receipt_sha256: SHA256
    model_artifact_id: UUID
    model_artifact_sha256: SHA256
    result_sha256: SHA256
    provider: Provider
    api_family: ApiFamily
    model_id: str = Field(min_length=1, max_length=500)
    price: PriceCard
    usage: TokenUsage
    actual_usd: USD
    day: date
    source_event_at: AwareDatetime
    checked_at: AwareDatetime
    content: CodeChangeContent
    content_sha256: SHA256
    changed_files: tuple[BuilderArtifact, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def exact_result_data(self) -> Self:
        header = self.header
        if (
            self.receipt_id != uuid5(header.action_id, "model-receipt-v1")
            or self.model_artifact_id != uuid5(header.action_id, str(header.parameters.request_id))
            or self.content_sha256 != canonical_sha256(self.content)
            or self.price.version != header.parameters.price_version
            or self.actual_usd
            != reconcile_cost(self.price, self.usage, now=self.source_event_at).amount_usd
            or not self.intent_created_at <= self.source_event_at <= self.checked_at
            or self.day != billing_day(self.intent_created_at)
            or len({row.path for row in self.changed_files}) != len(self.changed_files)
            or not {row.path for row in self.changed_files} <= set(header.allowed_write_paths)
        ):
            raise ValueError(
                "Published model-origin data differs from exact native/billing/source inputs"
            )
        return self


class PublishedCodingPatch(BrainContract):
    """Real Brain source receipts; no work acceptance, plan approval or native permit."""

    action_id: UUID
    request_id: UUID
    native_proposal_sha256: SHA256
    origin: IngestReceipt
    patch: IngestReceipt
    origin_sha256: SHA256
    patch_sha256: SHA256
    admission_sha256: SHA256
    company_completed: Literal[False] = False

    @model_validator(mode="after")
    def exact_pair(self) -> Self:
        if (
            self.origin.status != "accepted"
            or self.patch.status != "accepted"
            or any(row.company_id != self.company_id for row in (self.origin, self.patch))
            or self.origin.artifact.sha256 != self.origin_sha256
            or self.patch.artifact.sha256 != self.patch_sha256
            or self.origin.source.source_id
            != uuid5(self.action_id, "coding-model_origin-source-v1")
            or self.patch.source.source_id != uuid5(self.action_id, "coding-code_patch-source-v1")
        ):
            raise ValueError("Coding publication needs its exact accepted source pair")
        return self


@dataclass(frozen=True, slots=True)
class CodingPublicationRead:
    value: PublishedCodingPatch
    read_end_us: int
