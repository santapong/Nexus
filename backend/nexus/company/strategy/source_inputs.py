"""Same-session current source checks for original strategy inputs; no plan or effect authority."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.retrieval_records import bundles, heads
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.brain.source_models import BrainSource
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import (
    QualifiedFreshness,
    RegisteredSourcePolicies,
    require_qualified_time,
)
from nexus.company.management.native_report_inputs import native_manifest
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.contracts import StrategyCheckSnapshot
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


def _require_source_manifest(original: StrategyCheckSnapshot) -> None:
    ids = tuple(row.evidence.evidence_id for row in original.sources)
    require_acceptance(
        len(ids) == len(set(ids))
        and set(ids) == {row.evidence_id for row in original.inputs.evidence}
        and all(
            row.evidence.artifact in original.inputs.artifacts
            and row.evidence.source in original.inputs.contributors
            for row in original.sources
        )
    )


@dataclass(frozen=True)
class StrategySourceProtection:
    """Captured current windows only; the caller must recheck after all later awaits."""

    grants: tuple[ResourceGeneration, ...]
    freshness: tuple[QualifiedFreshness, ...]
    credential: AuthenticatedWorkerIdentity

    def require_time(self, now: datetime) -> None:
        require_qualified_time(self.freshness, now)
        require_acceptance(
            all(row.expires_at is None or row.expires_at > now for row in self.grants)
        )
        self.credential.require_time(now)


class StrategySourceInputs:
    """Reconcile original descriptions against current native records and registered policy."""

    def __init__(
        self, artifacts: BoundedArtifactReader, policies: RegisteredSourcePolicies
    ) -> None:
        self.artifacts, self.policies = artifacts, policies

    async def revalidate_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        original: StrategyCheckSnapshot,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> StrategySourceProtection:
        """Preserve original clocks/bytes while checking current source authority separately."""
        original = StrategyCheckSnapshot.model_validate(original.model_dump(warnings=False))
        require_acceptance(
            session.in_transaction()
            and control.company_id == scope.company_id == original.company_id
            and isinstance(credential, AuthenticatedWorkerIdentity)
            and credential.identity == identity
        )
        now = await db_now(session)
        require_acceptance(original.observed_at <= now)
        credential.require_time(now)
        await require_brain_scope(session, control, scope, identity)
        _require_source_manifest(original)
        for reference in original.inputs.artifacts:
            await self.artifacts.revalidate_artifact_reference(
                session, control, scope, identity, reference, await db_now(session)
            )
        manifest, _ = await native_manifest(
            session,
            scope,
            original.inputs.artifacts,
            original.inputs.contributors,
            original.inputs.evidence,
            original.inputs.required_resource_ids,
        )
        require_acceptance(manifest == original.inputs)
        await self._original_sources(session, scope, original)
        freshness = await self._freshness(session, scope, original)
        grants = await require_resources(
            session, scope, manifest.required_resource_ids, await db_now(session)
        )
        protection = StrategySourceProtection(grants, freshness, credential)
        protection.require_time(await db_now(session))
        return protection

    async def _original_sources(
        self, session: AsyncSession, scope: BrainReadScope, original: StrategyCheckSnapshot
    ) -> None:
        ids = tuple(row.evidence.evidence_id for row in original.sources)
        records = await bundles(session, scope, ids)
        current = {
            row.source_id: row
            for row in await heads(
                session, scope, tuple(row.evidence.source for row in original.sources)
            )
        }
        for source in original.sources:
            require_acceptance(
                source.head.source_id == source.evidence.source.source_id
                and source.head.current == source.evidence.source
                and source.head.source_id in current
            )
            bundle = records[source.evidence.evidence_id]
            policy = self._policy(bundle.source, bundle.artifact.media_type)
            require_acceptance(
                bundle.record() == source.evidence
                and bundle.artifact.raw_text == source.raw_text
                and current[source.head.source_id] == source.head
                and policy == source.source_policy
                and bundle.artifact.byte_length <= policy.max_bytes
                and source.head.observed_at <= original.observed_at
                and source.evidence.ingested_at <= original.observed_at
            )

    def _policy(self, row: BrainSource, media_type: str | None = None) -> SourcePolicy:
        policy = SourcePolicy.model_validate(self.policies.policy(row.source_symbol).model_dump())
        require_acceptance(
            row.source_symbol == policy.source_symbol
            and row.authority_profile == policy.authority_profile
            and row.data_classification == policy.data_classification
            and row.external_key in policy.allowed_external_keys
            and (media_type is None or media_type == policy.media_type)
        )
        return policy

    async def _freshness(
        self, session: AsyncSession, scope: BrainReadScope, original: StrategyCheckSnapshot
    ) -> tuple[QualifiedFreshness, ...]:
        current = await heads(session, scope, original.inputs.contributors)
        wanted = {row.source_id: row for row in original.inputs.contributors}
        require_acceptance(
            len(current) == len(wanted) == len(original.inputs.contributors)
            and {row.source_id for row in current} == set(wanted)
        )
        values: list[QualifiedFreshness] = []
        for head in current:
            row = await session.get(BrainSource, (scope.company_id, head.source_id))
            require_acceptance(row is not None and head.current == wanted[head.source_id])
            assert row is not None
            policy = self._policy(row)
            deadline = (
                head.observed_at + timedelta(seconds=policy.freshness_seconds)
                if policy.freshness_seconds is not None
                else None
            )
            require_acceptance(head.fresh_until == deadline)
            values.append(
                QualifiedFreshness(
                    head.source_id, policy, deadline, head.availability == "available"
                )
            )
        return tuple(values)
