"""Protected engineering check bytes retain both actual native result provenance closures."""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.engineering_contracts import ENGINEERING_RECIPE, EngineeringCheckResult
from nexus.builder.engineering_inputs import PreparedEngineeringInput
from nexus.builder.publication_support import append_inputs, require_replay_manifest
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.claims import DerivationRecord
from nexus.company.brain.derivation_support import save_derivation, validate_derivation
from nexus.company.brain.source_models import BrainArtifactRevision
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_provenance import reference_sources
from nexus.execution.runtime_support import db_now


class EngineeringProofStorage:
    def __init__(
        self, blobs: ProtectedBlobStore, target: ResourceRef, policy: SourcePolicy
    ) -> None:
        self.blobs, self.target, self.policy = blobs, target, policy

    def reference(self, result: EngineeringCheckResult) -> ArtifactRevisionRef:
        raw = result.model_dump_json().encode()
        if len(raw) > 16384:
            raise ValueError("Engineering check proof exceeds its bound")
        key = uuid5(
            result.verifier_action_id,
            f"engineering-proof:{result.target_sha256}:{result.input_sha256}",
        )
        return ArtifactRevisionRef(
            company_id=result.company_id,
            artifact_id=key,
            artifact_revision_id=uuid5(key, "revision-v1"),
            revision=ENGINEERING_RECIPE,
            sha256=hashlib.sha256(raw).hexdigest(),
            byte_length=len(raw),
        )

    async def save(self, result: EngineeringCheckResult) -> ArtifactRevisionRef:
        ref = self.reference(result)
        await self.blobs.save(ref, result.model_dump_json().encode())
        return ref

    async def require_stored_locked(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        prepared: PreparedEngineeringInput,
        result: EngineeringCheckResult,
        reference: ArtifactRevisionRef,
    ) -> None:
        require_acceptance(
            await session.get(
                BrainArtifactRevision, (scope.company_id, reference.artifact_revision_id)
            )
            is not None
        )
        await self.append_locked(session, scope, prepared, result, reference)

    async def append_locked(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        prepared: PreparedEngineeringInput,
        result: EngineeringCheckResult,
        reference: ArtifactRevisionRef,
    ) -> None:
        require_acceptance(
            reference == self.reference(result) and self.target.company_id == scope.company_id
        )
        previous = await session.get(
            BrainArtifactRevision, (scope.company_id, reference.artifact_revision_id)
        )
        recorded = previous.recorded_at if previous is not None else await db_now(session)
        derivation, originals, resources = await self._lineage(
            session, scope, prepared, reference, recorded
        )
        if previous is not None:
            self._require_existing(previous, reference, derivation, result)
            await require_replay_manifest(session, reference, derivation, originals, resources)
            return
        session.add(
            BrainArtifactRevision(
                company_id=scope.company_id,
                artifact_revision_id=reference.artifact_revision_id,
                artifact_id=reference.artifact_id,
                revision=reference.revision,
                resource_id=self.target.resource_id,
                media_type="application/json",
                storage_symbol=self.blobs.storage_symbol,
                raw_text=result.model_dump_json(),
                sha256=reference.sha256,
                byte_length=reference.byte_length,
                derivation_id=derivation.derivation_id,
                data_classification=self.policy.data_classification,
                recorded_at=derivation.recorded_at,
            )
        )
        await session.flush()
        await save_derivation(session, derivation)
        await append_inputs(session, reference, originals, resources)

    def _require_existing(
        self,
        previous: BrainArtifactRevision,
        reference: ArtifactRevisionRef,
        derivation: DerivationRecord,
        result: EngineeringCheckResult,
    ) -> None:
        require_acceptance(
            previous.sha256 == reference.sha256
            and previous.byte_length == reference.byte_length
            and previous.raw_text == result.model_dump_json()
            and previous.resource_id == self.target.resource_id
            and previous.derivation_id == derivation.derivation_id
            and previous.data_classification == self.policy.data_classification
            and previous.media_type == "application/json"
            and previous.storage_symbol == self.blobs.storage_symbol
        )

    async def _lineage(
        self,
        session: AsyncSession,
        scope: BrainReadScope,
        prepared: PreparedEngineeringInput,
        reference: ArtifactRevisionRef,
        recorded: datetime,
    ) -> tuple[DerivationRecord, tuple[BrainArtifactRevision, ...], tuple[UUID, ...]]:
        refs = tuple(row.artifact for row in prepared.artifacts)
        _, resources = await reference_sources(session, scope, refs)
        await require_resources(
            session,
            scope,
            tuple(sorted({*resources, self.target.resource_id})),
            await db_now(session),
        )
        roots = {
            head.source_id: head.current for row in prepared.artifacts for head in row.source_heads
        }
        require_acceptance(0 < len(roots) <= 32)
        derivation = DerivationRecord(
            company_id=scope.company_id,
            derivation_id=uuid5(reference.artifact_id, "derivation-v1"),
            artifact=reference,
            recipe_version=ENGINEERING_RECIPE,
            kind="context",
            contributors=tuple(roots[key] for key in sorted(roots)),
            evidence=(),
            recorded_at=recorded,
        )
        await validate_derivation(
            session,
            scope,
            derivation,
            reference,
            self.target.resource_id,
            self.policy,
            await db_now(session),
        )
        originals = []
        for ref in refs:
            row = await session.get(
                BrainArtifactRevision, (scope.company_id, ref.artifact_revision_id)
            )
            require_acceptance(row is not None)
            assert row is not None
            originals.append(row)
        return derivation, tuple(originals), resources
