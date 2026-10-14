"""Actual known-output worker services; source mapping is trusted fixed fixture composition."""

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
from nexus.tests.engineering_fixture import EngineeringScenario

TEST_SIGNING_KEY = "engineering-worker-public-synthetic-signing-key-at-least-64-characters-long"


class FixtureWorkerCredential:
    """Public synthetic credential exercises real verification; it has no production authority."""

    def __init__(self, item: EngineeringScenario, *, expires_seconds: int = 300) -> None:
        job = item.verifier.spec.job
        now = int(datetime.now(UTC).timestamp())
        self.value = SecretStr(
            jwt.encode(
                {
                    "sub": str(job.actor_id),
                    "workspace_id": str(job.workspace_id),
                    "iat": now - 1,
                    "exp": now + expires_seconds,
                },
                TEST_SIGNING_KEY,
                algorithm="HS256",
            )
        )

    async def credential(self) -> SecretStr:
        return self.value


class FixtureEngineeringSource:
    """Map only the already registered scenario source; no input-selected repository path."""

    def __init__(self, item: EngineeringScenario, *, fail: bool = False) -> None:
        self.item, self.fail = item, fail

    def resolve(
        self,
        binding: RunBinding,
        spec: BuilderExecutionSpec,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
    ) -> BuilderSourceGuard:
        if self.fail:
            raise ValueError("Synthetic configured source unavailable")
        original = self.item.verifier_guard
        return BuilderSourceGuard(
            spec,
            original.policy,
            lease,
            identity,
            original.source,
            original.artifacts,
            original.freshness,
            original.catalog,
        )


def worker_services(
    item: EngineeringScenario, *, fail_source: bool = False
) -> EngineeringWorkerServices:
    """New actual worker gets no new allowance, action, intent or receipt."""
    return EngineeringWorkerServices(
        factory=item.runner.factory,
        catalog=item.catalog,
        runner=item.runner,
        acceptance=item.acceptance,
        recovery=EngineeringAcceptanceRecovery(
            item.runner.factory, item.catalog, item.acceptance.inputs, item.acceptance.proof
        ),
        identities=NotificationWorkerIdentities(
            FixtureWorkerCredential(item), SecretStr(TEST_SIGNING_KEY), enabled=True
        ),
        sources=FixtureEngineeringSource(item, fail=fail_source),
        worker_id=uuid4(),
    )
