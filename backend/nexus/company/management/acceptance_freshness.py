"""Registered server source policies distinguish qualified no-TTL from unknown freshness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.artifact_contracts import ArtifactSlice
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import brain_transaction
from nexus.company.brain.source_models import BrainSource, BrainSourceHead
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_errors import AcceptanceDeniedError, require_acceptance
from nexus.company.management.acceptance_provenance import reference_sources
from nexus.company.management.historical_reference_provenance import historical_reference_sources
from nexus.execution.runtime_support import db_now


class RegisteredSourcePolicies(Protocol):
    """Process-configured registry lookup, never a request's freshness flag/profile."""

    def policy(self, symbol: str) -> SourcePolicy: ...


@dataclass(frozen=True)
class QualifiedFreshness:
    source_id: UUID
    policy: SourcePolicy
    fresh_until: datetime | None
    available: bool


def require_qualified_time(values: tuple[QualifiedFreshness, ...], now: datetime) -> None:
    for value in values:
        require_acceptance(value.available)
        if value.policy.freshness_seconds is None:
            require_acceptance(value.fresh_until is None)
        else:
            require_acceptance(value.fresh_until is not None and value.fresh_until > now)


class RegisteredSourceFreshness:
    def __init__(
        self, factory: async_sessionmaker[AsyncSession], policies: RegisteredSourcePolicies
    ) -> None:
        self._factory, self._policies = factory, policies

    async def prepare(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        artifacts: tuple[ArtifactSlice, ...],
    ) -> tuple[QualifiedFreshness, ...]:
        ids = tuple(
            sorted({head.source_id for artifact in artifacts for head in artifact.source_heads})
        )
        require_acceptance(0 < len(ids) <= 64)
        async with brain_transaction(self._factory, scope, identity) as (session, _, now):
            result = await self._resolve(session, scope, ids)
            require_qualified_time(result, now)
            return result

    async def revalidate(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        previous: tuple[QualifiedFreshness, ...],
        now: datetime,
    ) -> None:
        current = await self._resolve(session, scope, tuple(row.source_id for row in previous))
        require_acceptance(current == previous)
        require_qualified_time(current, now)

    async def capture_plan_heads_locked(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        source_ids: tuple[UUID, ...],
        now: datetime,
    ) -> tuple[QualifiedFreshness, ...]:
        """Metadata-only qualification; caller retains actual owner/control/READ admission gates."""
        require_acceptance(session.in_transaction() and now.utcoffset() is not None)
        require_acceptance(len(source_ids) <= 32 and len(set(source_ids)) == len(source_ids))
        result = await self._resolve(session, scope, source_ids)
        require_acceptance(tuple(row.source_id for row in result) == source_ids)
        require_qualified_time(result, await db_now(session))
        return result

    async def revalidate_references(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        references: tuple[ArtifactRevisionRef, ...],
        now: datetime,
    ) -> None:
        """DB-only qualifier; caller owns CompanyControl and signed scope/lease gates."""
        ids, resources = await reference_sources(session, scope, references)
        current = await self._resolve(session, scope, ids)
        checked = await db_now(session)
        require_qualified_time(current, checked)
        grants = await require_resources(session, scope, resources, checked)
        final = await db_now(session)
        require_qualified_time(current, final)
        require_acceptance(all(row.expires_at is None or row.expires_at > final for row in grants))

    async def revalidate_historical_references(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        references: tuple[ArtifactRevisionRef, ...],
        now: datetime,
    ) -> tuple[datetime, ...]:
        """Explicit obsolete-history policy qualification against current heads and grants."""
        ids, resources = await historical_reference_sources(session, scope, references)
        current = await self._resolve(session, scope, ids)
        checked = await db_now(session)
        require_qualified_time(current, checked)
        grants = await require_resources(session, scope, resources, checked)
        deadlines = tuple(row.fresh_until for row in current if row.fresh_until is not None)
        deadlines += tuple(row.expires_at for row in grants if row.expires_at is not None)
        final = await db_now(session)
        require_qualified_time(current, final)
        require_acceptance(all(value > final for value in deadlines))
        return tuple(sorted(set(deadlines)))

    async def _resolve(
        self, session: AsyncSession, scope: BrainReadScope, ids: tuple[UUID, ...]
    ) -> tuple[QualifiedFreshness, ...]:
        result: list[QualifiedFreshness] = []
        for source_id in ids:
            source = await session.get(BrainSource, (scope.company_id, source_id))
            head = await session.get(BrainSourceHead, (scope.company_id, source_id))
            require_acceptance(source is not None and head is not None)
            assert source is not None and head is not None
            try:
                policy = SourcePolicy.model_validate_json(
                    self._policies.policy(source.source_symbol).model_dump_json()
                )
            except (LookupError, ValueError) as exc:
                raise AcceptanceDeniedError("Registered source policy is unavailable") from exc
            require_acceptance(
                source.source_symbol == policy.source_symbol
                and source.authority_profile == policy.authority_profile
                and source.data_classification == policy.data_classification
                and source.external_key in policy.allowed_external_keys
            )
            result.append(
                QualifiedFreshness(
                    source_id, policy, head.fresh_until, head.availability == "available"
                )
            )
        return tuple(result)
