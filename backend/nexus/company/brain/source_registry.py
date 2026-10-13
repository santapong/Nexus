"""Explicit trusted source symbols; requests cannot choose paths, authority or classification."""

from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field

from nexus.company.brain.base import BrainContract, Name, SourceTime, Symbol, ValueContract
from nexus.company.brain.claims import DerivationRecord
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.sources import SourceRegistration, UTF8Span


class SourcePolicy(ValueContract):
    """Operator-owned immutable parser/source recipe, not a decoded ingestion request."""

    source_symbol: Symbol
    authority_profile: Symbol
    data_classification: Literal["public", "internal", "confidential", "restricted"]
    origin_kind: Literal["direct", "derived"] = "direct"
    media_type: Literal["text/plain", "text/markdown", "application/json"]
    parser_version: Symbol
    chunker_version: Symbol
    search_config: Literal["simple", "english"]
    freshness_seconds: int | None = Field(ge=1, le=86_400, strict=True)
    allowed_external_keys: frozenset[Name] = frozenset()
    max_bytes: int = Field(default=2_097_152, ge=1, le=2_097_152, strict=True)
    chunk_bytes: int = Field(default=8192, ge=32, le=8192, strict=True)
    max_chunks: int = Field(default=256, ge=1, le=256, strict=True)
    parse_timeout_seconds: int = Field(default=10, ge=1, le=10, strict=True)


class SourceSnapshot(BrainContract):
    """Configured source adapter's exact bytes and dates; contains no authority grants."""

    source_id: UUID
    source_symbol: Symbol
    external_key: Name
    revision: Name
    raw_bytes: bytes = Field(min_length=1, max_length=2_097_152)
    source_event: SourceTime
    source_author: Name | None = None
    sections: tuple[UTF8Span, ...] = Field(default=(), max_length=256)
    derivation: DerivationRecord | None = None


class RegisteredSourceReader(Protocol):
    """Server-owned exact source mapping; no arbitrary fetch/local path interpretation."""

    async def read(self, source: SourceRegistration, revision: str) -> SourceSnapshot:
        """Read only the configured source key/revision and return truthful source precision."""
        ...


class SourceRegistry:
    """No defaults or live sources; the operator must supply both policies and a named reader."""

    def __init__(self, policies: tuple[SourcePolicy, ...], reader: RegisteredSourceReader) -> None:
        self._policies = {
            value.source_symbol: SourcePolicy.model_validate(value.model_dump())
            for value in policies
        }
        if len(self._policies) != len(policies) or reader is None:
            raise ValueError(
                "Source registry requires distinct explicit symbols and a trusted reader"
            )
        self._reader = reader

    def policy(self, symbol: str) -> SourcePolicy:
        value = self._policies.get(symbol)
        if value is None:
            raise BrainDeniedError("Registered Brain source is unavailable")
        return value

    def require_source(self, source: SourceRegistration) -> SourcePolicy:
        value = self.policy(source.source_symbol)
        if source.external_key not in value.allowed_external_keys:
            raise BrainDeniedError("Registered Brain source is unavailable")
        return value

    async def read(self, source: SourceRegistration, revision: str) -> SourceSnapshot:
        policy = self.require_source(source)
        result = await self._reader.read(source, revision)
        result = SourceSnapshot.model_validate(result.model_dump())
        if (
            result.company_id,
            result.source_id,
            result.source_symbol,
            result.external_key,
            result.revision,
        ) != (
            source.company_id,
            source.source_id,
            source.source_symbol,
            source.external_key,
            revision,
        ) or len(result.raw_bytes) > policy.max_bytes:
            raise BrainDeniedError("Registered source adapter binding is inconsistent")
        if (result.derivation is not None) != (policy.origin_kind == "derived"):
            raise BrainDeniedError("Registered derivative requires its complete source manifest")
        return result
