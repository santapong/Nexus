"""Publish a real protected result summary with exact complete input/privacy edges."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.execution_contracts import BuilderRunResult
from nexus.builder.publication_support import (
    append_inputs,
    publication_inputs,
    recipient_windows,
    require_publication_intent,
    require_replay_manifest,
)
from nexus.builder.result_store import BuilderResultStore
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.claims import DerivationRecord
from nexus.company.brain.derivation_support import save_derivation, validate_derivation
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRef, SourceRevisionRef
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)


class BuilderArtifactPublisher:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        blobs: ProtectedBlobStore,
        target: ResourceRef,
        policy: SourcePolicy,
    ) -> None:
        self.factory, self.blobs, self.target, self.policy = factory, blobs, target, policy

    def payload(self, result: BuilderRunResult) -> bytes:
        return json.dumps(
            {
                "result_sha256": BuilderResultStore.digest(result),
                "spec": result.spec.model_dump(mode="json"),
                "proposal_sha256": result.proposal_sha256,
                "intent_fence": result.intent_fence,
                "outcome": result.outcome,
                "commands": [row.model_dump(mode="json") for row in result.commands],
                "artifacts": [row.metadata.model_dump(mode="json") for row in result.artifacts],
                "logs": [row.metadata.model_dump(mode="json") for row in result.logs],
                "limitations": result.limitations,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    def reference(self, result: BuilderRunResult) -> ArtifactRevisionRef:
        job = result.spec.job
        artifact = uuid5(job.action_id, "native-builder-protected-result-v1")
        raw = self.payload(result)
        if len(raw) > 262144:
            raise ValueError("Builder protected summary exceeds its bound")
        return ArtifactRevisionRef(
            company_id=job.company_id,
            artifact_id=artifact,
            artifact_revision_id=uuid5(artifact, "revision-v1"),
            revision="native-builder-v1",
            sha256=hashlib.sha256(raw).hexdigest(),
            byte_length=len(raw),
        )

    async def publish(
        self,
        result: BuilderRunResult,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        guard: BuilderSourceGuard,
    ) -> ArtifactRevisionRef:
        reference = self.reference(result)
        await self.blobs.save(reference, self.payload(result))
        async with runtime_transaction(
            self.factory,
            lease_scope(lease),
            identity,
            allow_paused=lease.mode == "reconcile",
            allow_inactive=lease.mode == "reconcile",
        ) as (session, control, _):
            work = await execution_row(session, lease_scope(lease))
            now = await db_now(session)
            require_lease(work, lease, now, execute=lease.mode == "execute")
            await require_publication_intent(session, lease, result, guard, self.target)
            windows = await guard.disclosure_windows(session, control)
            originals, refs, resources = await publication_inputs(session, guard)
            windows = (*windows, *await recipient_windows(session, guard, self.target, resources))
            grants = await require_resources(
                session,
                guard.scope(),
                tuple(sorted({*resources, self.target.resource_id})),
                await db_now(session),
            )
            derivation = self.derivation(result, reference, refs)
            await validate_derivation(
                session,
                guard.scope(),
                derivation,
                reference,
                self.target.resource_id,
                self.policy,
                await db_now(session),
            )
            await self.append(session, result, reference, derivation, originals, resources)
            final = await db_now(session)
            require_lease(work, lease, final, execute=lease.mode == "execute")
            if any(value <= final for value in windows) or any(
                row.expires_at is not None and row.expires_at <= final for row in grants
            ):
                raise ValueError("Builder output source/recipient expiry crossed publication")
        return reference

    async def append(
        self,
        session: AsyncSession,
        result: BuilderRunResult,
        reference: ArtifactRevisionRef,
        derivation: DerivationRecord,
        originals: tuple[BrainArtifactRevision, ...],
        resources: tuple[UUID, ...],
    ) -> None:
        existing = await session.get(
            BrainArtifactRevision, (reference.company_id, reference.artifact_revision_id)
        )
        expected = self.artifact_row(result, reference, derivation)
        if existing is not None:
            fields = (
                "company_id",
                "artifact_revision_id",
                "artifact_id",
                "revision",
                "resource_id",
                "media_type",
                "storage_symbol",
                "raw_text",
                "sha256",
                "byte_length",
                "derivation_id",
                "data_classification",
                "recorded_at",
            )
            if any(getattr(existing, key) != getattr(expected, key) for key in fields):
                raise ValueError("Builder protected output replay differs")
            await require_replay_manifest(session, reference, derivation, originals, resources)
            return
        session.add(expected)
        await session.flush()
        await save_derivation(session, derivation)
        await append_inputs(session, reference, originals, resources)

    def derivation(
        self,
        result: BuilderRunResult,
        reference: ArtifactRevisionRef,
        refs: tuple[SourceRevisionRef, ...],
    ) -> DerivationRecord:
        return DerivationRecord(
            company_id=reference.company_id,
            derivation_id=uuid5(reference.artifact_id, "derivation-v1"),
            artifact=reference,
            recipe_version="native-builder-result-v1",
            kind="context",
            contributors=refs,
            evidence=(),
            recorded_at=result.recorded_at,
        )

    def artifact_row(
        self, result: BuilderRunResult, reference: ArtifactRevisionRef, derivation: DerivationRecord
    ) -> BrainArtifactRevision:
        return BrainArtifactRevision(
            company_id=reference.company_id,
            artifact_revision_id=reference.artifact_revision_id,
            artifact_id=reference.artifact_id,
            revision=reference.revision,
            resource_id=self.target.resource_id,
            media_type="application/json",
            storage_symbol=self.blobs.storage_symbol,
            raw_text=self.payload(result).decode(),
            sha256=reference.sha256,
            byte_length=reference.byte_length,
            derivation_id=derivation.derivation_id,
            data_classification=self.policy.data_classification,
            recorded_at=result.recorded_at,
        )
