"""Reconstruct only reviewed synthetic engineering services from fixed process fixture config."""

from pathlib import Path
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.engineering_acceptance import EngineeringWorkAcceptanceStore
from nexus.builder.engineering_acceptance_recovery import EngineeringAcceptanceRecovery
from nexus.builder.engineering_artifacts import EngineeringArtifactPublisher
from nexus.builder.engineering_inputs import RegisteredEngineeringInputs
from nexus.builder.engineering_proof import EngineeringProofStorage
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.source_guard import BuilderSourceGuard, RegisteredBuilderSource
from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.plans import RunBinding
from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.engineering_worker_services import (
    EngineeringWorkerHook,
    EngineeringWorkerServices,
)
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_store import ExecutionStore
from nexus.tests.engineering_process_config import EngineeringProcessConfig
from nexus.tests.engineering_process_scope import require_process_root
from nexus.tests.engineering_process_wrappers import (
    ObservedEffects,
    ObservedEngineeringRunner,
    ObservedResults,
)
from nexus.tests.engineering_worker_fixture import TEST_SIGNING_KEY
from nexus.tests.integration.management_acceptance_source_fixture import Policies


class ProcessSource:
    def __init__(
        self,
        config: EngineeringProcessConfig,
        reader: BoundedArtifactReader,
        freshness: RegisteredSourceFreshness,
    ) -> None:
        self.config, self.reader, self.freshness = config, reader, freshness

    def resolve(
        self,
        binding: RunBinding,
        spec: BuilderExecutionSpec,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
    ) -> BuilderSourceGuard:
        if binding != self.config.verifier_binding or spec != self.config.verifier_spec:
            raise ValueError("Reviewed process source identity differs")
        return BuilderSourceGuard(
            spec,
            self.config.policy,
            lease,
            identity,
            RegisteredBuilderSource(self.config.source_root, self.config.source_metadata),
            self.reader,
            self.freshness,
            self.config.catalog,
        )


def compose_process_services(
    factory: async_sessionmaker[AsyncSession],
    config: EngineeringProcessConfig,
    root: Path,
    command: SegmentCommand,
    worker_id: UUID,
    hook: EngineeringWorkerHook,
) -> EngineeringWorkerServices:
    # Keep this >50-line fixture composition together so the same reader, policy,
    # protected namespaces and actual factory reach every unchanged runtime gate.
    require_process_root(config.database, root, existing=True)
    if config.task_root != root or config.command != command:
        raise ValueError("Engineering process composition differs from reviewed command/root")
    policies = Policies()
    policies.values = {p.source_symbol: p for p in config.policies}
    blobs = ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1")
    reader = BoundedArtifactReader(factory, blobs)
    freshness = RegisteredSourceFreshness(factory, policies)
    execution = ExecutionStore(
        factory,
        management_catalog=config.catalog,
        management_artifacts=reader,
        management_freshness=freshness,
    )
    effects = ObservedEffects(
        factory,
        management_catalog=config.catalog,
        management_artifacts=reader,
        management_freshness=freshness,
        hook=hook,
        command=command,
    )
    jobs = root / "jobs"
    publisher = EngineeringArtifactPublisher(
        factory, blobs, config.output_target, policies.policy("fixture.source.v1"), jobs
    )
    results = ObservedResults(root / "results", hook, command)
    runner = ObservedEngineeringRunner(
        factory,
        execution,
        effects,
        config.policy,
        config.capabilities,
        config.image_id,
        results,
        jobs,
        publisher,
        hook=hook,
        command=command,
    )
    inputs = RegisteredEngineeringInputs(factory, reader, results, (config.declaration,), freshness)
    proof = EngineeringProofStorage(
        blobs, config.proof_target, policies.policy("fixture.source.v1")
    )
    return EngineeringWorkerServices(
        factory=factory,
        catalog=config.catalog,
        runner=runner,
        acceptance=EngineeringWorkAcceptanceStore(factory, config.catalog, inputs, proof),
        recovery=EngineeringAcceptanceRecovery(factory, config.catalog, inputs, proof),
        identities=NotificationWorkerIdentities(
            ProcessCredential(config), SecretStr(TEST_SIGNING_KEY), enabled=True
        ),
        sources=ProcessSource(config, reader, freshness),
        worker_id=worker_id,
        lease_ttl_seconds=config.lease_ttl_seconds,
        hook=hook,
    )


class ProcessCredential:
    def __init__(self, config: EngineeringProcessConfig) -> None:
        from datetime import UTC, datetime

        import jwt

        binding = config.verifier_binding
        now = int(datetime.now(UTC).timestamp())
        self.value = SecretStr(
            jwt.encode(
                {
                    "sub": str(binding.actor_id),
                    "workspace_id": str(binding.workspace_id),
                    "iat": now - 1,
                    "exp": now + 300,
                },
                TEST_SIGNING_KEY,
                algorithm="HS256",
            )
        )

    async def credential(self) -> SecretStr:
        return self.value
