"""Source-backed engineering summary includes actual private pre-intent inventory witness."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.artifact_publisher import BuilderArtifactPublisher
from nexus.builder.engineering_contracts import EngineeringSourceWitness
from nexus.builder.engineering_witness import load_witness
from nexus.builder.execution_contracts import BuilderRunResult
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.source_registry import SourcePolicy
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.execution.runtime_contracts import ExecutionLease


class EngineeringArtifactPublisher(BuilderArtifactPublisher):
    jobs_root: Path
    witnesses: dict[UUID, EngineeringSourceWitness]

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        blobs: ProtectedBlobStore,
        target: ResourceRef,
        policy: SourcePolicy,
        jobs_root: Path,
    ) -> None:
        super().__init__(factory, blobs, target, policy)
        if not jobs_root.is_absolute() or jobs_root.resolve(strict=True) != jobs_root:
            raise ValueError("Engineering witness root is not an actual managed directory")
        self.jobs_root, self.witnesses = jobs_root, {}

    async def prepare_witness(self, result: BuilderRunResult) -> None:
        job = result.spec.job
        root = self.jobs_root / f"{job.company_id.hex}-{job.action_id.hex}"
        self.witnesses[job.action_id] = await asyncio.to_thread(load_witness, root, result.spec)

    def payload(self, result: BuilderRunResult) -> bytes:
        witness = self.witnesses.get(result.spec.job.action_id)
        if witness is None:
            raise ValueError("Engineering publication needs its actual stored source witness")
        return json.dumps(
            {
                **json.loads(super().payload(result)),
                "engineering_source_witness": witness.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    async def publish(
        self,
        result: BuilderRunResult,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        guard: BuilderSourceGuard,
    ) -> ArtifactRevisionRef:
        await self.prepare_witness(result)
        try:
            return await super().publish(result, lease, identity, guard)
        finally:
            self.witnesses.pop(result.spec.job.action_id, None)
