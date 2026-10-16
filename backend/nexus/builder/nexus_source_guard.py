"""One genuine actor credential bound to the existing native source/containment guard."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.contained_services import ContainmentServices
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.nexus_cycle_admission import validate_nexus_catalog
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl, JournalAction


class NexusBuilderSourceGuard(BuilderSourceGuard):
    """Existing source/native checks plus original finite credential, never a copied permission."""

    def __init__(
        self, original: BuilderSourceGuard, credential: AuthenticatedWorkerIdentity
    ) -> None:
        if type(original) is not BuilderSourceGuard or not isinstance(
            credential, AuthenticatedWorkerIdentity
        ):
            raise ValueError("Nexus builder needs its actual source guard and credential")
        super().__init__(
            original.spec,
            original.policy,
            original.lease,
            original.identity,
            original.source,
            original.artifacts,
            original.freshness,
            original.catalog,
            containment=original.containment,
        )
        self.credential = credential
        self._original = original
        self._objects = self._identities()
        self._pin = self._fingerprint()
        self.require_composition()

    def _identities(self) -> tuple[object, ...]:
        return (
            self._original,
            self.spec,
            self.policy,
            self.lease,
            self.identity,
            self.source,
            self.artifacts,
            self.freshness,
            self.catalog,
            self.containment,
            self.credential,
            *(
                (
                    self.containment.expectation,
                    self.containment.store,
                    self.containment.parents,
                    self.containment.process,
                    self.containment.process.discovery,
                    self.containment.process.stopper,
                    self.containment.process.stopper.io,
                    self.containment.cleanup,
                    self.containment.diagnostics,
                )
                if self.containment is not None
                else ()
            ),
        )

    def _fingerprint(self) -> tuple[object, ...]:
        return (
            self.spec.model_dump_json(),
            self.policy.model_dump_json(),
            self.lease.model_dump_json(),
            self.identity.model_dump_json(),
            self.source,
            canonical_sha256(self.catalog),
            self.artifacts.factory,
            self.freshness._factory,
            self.credential.identity,
            self.credential.issued_at,
            self.credential.expires_at,
            self.containment.method_sha256 if self.containment is not None else None,
        )

    def require_composition(self) -> None:
        if (
            any(a is not b for a, b in zip(self._objects, self._identities(), strict=True))
            or self._fingerprint() != self._pin
        ):
            raise ValueError("Nexus builder original composition changed")
        original = self._original
        if any(
            getattr(original, name) is not getattr(self, name)
            for name in (
                "spec",
                "policy",
                "lease",
                "identity",
                "source",
                "artifacts",
                "freshness",
                "catalog",
                "containment",
            )
        ):
            raise ValueError("Nexus original source guard was replaced")
        admission = validate_nexus_catalog(self.catalog.nexus_cycle_admission, self.catalog)
        if (
            admission is None
            or self.credential.identity != self.identity
            or self.lease.expires_at > self.credential.expires_at
        ):
            raise ValueError("Nexus builder credential does not cover its original lease")
        expected = next(
            (
                slot.child.binding
                for slot in admission.slots[1:3]
                if slot.work.task_id == self.lease.task_id
            ),
            None,
        )
        if expected is None or (
            expected.company_id,
            expected.task_id,
            expected.trace_id,
            expected.run_id,
            expected.actor_id,
            expected.workspace_id,
        ) != (
            self.lease.company_id,
            self.lease.task_id,
            self.lease.trace_id,
            self.lease.run_id,
            self.lease.actor_id,
            self.lease.workspace_id,
        ):
            raise ValueError("Nexus builder is not its actual configured E/EV role")
        if type(self.containment) is not ContainmentServices:
            raise ValueError("Nexus native builder requires actual containment")
        self.containment.require_policy(self.spec, self.policy)
        if self.artifacts.factory is not self.freshness._factory:
            raise ValueError("Nexus builder source readers use different factories")

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        self.require_composition()
        self.credential.require_time(now)
        await super().validate(session, control, work, action, now)
        self.validate_time(await db_now(session))

    def validate_time(self, now: datetime) -> None:
        self.require_composition()
        self.credential.require_time(now)
        super().validate_time(now)
