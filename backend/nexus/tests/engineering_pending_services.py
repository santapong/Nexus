"""Process-local services for an actual approved pending verifier; no output or permit is seeded."""

from datetime import UTC, datetime
from uuid import uuid4

import jwt
from pydantic import SecretStr

from nexus.builder.engineering_acceptance_recovery import EngineeringAcceptanceRecovery
from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.access import VerifiedIdentity
from nexus.company.management.plans import RunBinding
from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.execution.engineering_worker_services import EngineeringWorkerServices
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.tests.engineering_pending_contracts import PendingEngineeringScenario
from nexus.tests.engineering_worker_fixture import TEST_SIGNING_KEY


class PendingCredential:
    """Create one public synthetic test token; repeated acquisition returns identical bytes."""

    def __init__(self, item: PendingEngineeringScenario, seconds: int) -> None:
        binding = item.verifier_binding
        now = int(datetime.now(UTC).timestamp())
        self.value = SecretStr(
            jwt.encode(
                {
                    "sub": str(binding.actor_id),
                    "workspace_id": str(binding.workspace_id),
                    "iat": now - 1,
                    "exp": now + seconds,
                },
                TEST_SIGNING_KEY,
                algorithm="HS256",
            )
        )

    async def credential(self) -> SecretStr:
        return self.value


class PendingSource:
    def __init__(self, item: PendingEngineeringScenario) -> None:
        self.item = item

    def resolve(
        self,
        binding: RunBinding,
        spec: BuilderExecutionSpec,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
    ) -> BuilderSourceGuard:
        if binding != self.item.verifier_binding or spec != self.item.verifier_spec:
            raise ValueError("Pending engineering source mapping differs")
        return BuilderSourceGuard(
            spec,
            self.item.runner.policy,
            lease,
            identity,
            self.item.source,
            self.item.artifacts,
            self.item.freshness,
            self.item.catalog,
        )


def pending_services(
    item: PendingEngineeringScenario, *, credential_seconds: int = 300
) -> EngineeringWorkerServices:
    return EngineeringWorkerServices(
        factory=item.runner.factory,
        catalog=item.catalog,
        runner=item.runner,
        acceptance=item.acceptance,
        recovery=EngineeringAcceptanceRecovery(
            item.runner.factory, item.catalog, item.acceptance.inputs, item.acceptance.proof
        ),
        identities=NotificationWorkerIdentities(
            PendingCredential(item, credential_seconds), SecretStr(TEST_SIGNING_KEY), enabled=True
        ),
        sources=PendingSource(item),
        worker_id=uuid4(),
    )
