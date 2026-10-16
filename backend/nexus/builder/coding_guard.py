"""Exact current native E/EV guard consumes a real issued C-origin read, never a DTO."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.coding_templates import (
    CodingBuilderTemplate,
    checked_template,
    require_coding_builder_spec,
)
from nexus.builder.contained_services import ContainmentServices
from nexus.builder.source_guard import BuilderSourceGuard
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_publication_origin import (
    CodingOriginRead,
    CodingPublicationOriginReader,
)
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl, JournalAction


class CodingBuilderSourceGuard(BuilderSourceGuard):
    """Sealed actual original source graph and finite credential for one exact E/EV job."""

    def __init__(
        self,
        original: BuilderSourceGuard,
        credential: AuthenticatedWorkerIdentity,
        reader: CodingPublicationOriginReader,
        template: CodingBuilderTemplate,
        proof: CodingOriginRead,
    ) -> None:
        if (
            type(original) is not BuilderSourceGuard
            or type(reader) is not CodingPublicationOriginReader
        ):
            raise ValueError("Coding native guard requires actual concrete source and reader")
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
        self.credential, self.reader, self.template, self.proof = (
            credential,
            reader,
            checked_template(template),
            proof,
        )
        self._original = original
        self._objects = self._identities()
        self._pin = self._fingerprint()
        self._current_end = proof.read_end_us
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
            self.reader,
            self.reader.factory,
            self.reader.artifacts,
            self.reader.freshness,
            self.proof,
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
            canonical_sha256(self.spec),
            canonical_sha256(self.policy),
            self.lease.model_dump_json(),
            self.identity.model_dump_json(),
            self.source,
            canonical_sha256(self.catalog),
            canonical_sha256(self.template),
            self.credential.identity,
            self.credential.issued_at,
            self.credential.expires_at,
            self.artifacts.factory,
            self.freshness._factory,
            self.containment.method_sha256 if self.containment else None,
            canonical_sha256(self.containment.expectation) if self.containment else None,
        )

    def require_composition(self) -> None:
        """Native shape calls this before and after awaits; original proof is not replaceable."""
        if (
            any(a is not b for a, b in zip(self._objects, self._identities(), strict=True))
            or self._pin != self._fingerprint()
        ):
            raise ValueError("Original coding source/native guard changed")
        if any(
            getattr(self._original, key) is not getattr(self, key)
            for key in (
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
            raise ValueError("Original coding source resolver changed")
        self.reader.require_loaded(self.proof, self.lease, self.credential, self.spec)
        if (
            self.reader.artifacts is not self.artifacts
            or self.reader.freshness is not self.freshness
            or self.reader.catalog is not self.catalog
            or self.credential.identity != self.identity
            or type(self.containment) is not ContainmentServices
        ):
            raise ValueError("Coding native source graph or actor differs")
        binding = next(
            row.child.binding
            for row in self.reader.admission.slots[5:7]
            if row.work.task_id == self.lease.task_id
        )
        require_coding_builder_spec(
            self.template, binding, self.spec, self.policy, self.source.metadata
        )
        self.containment.require_policy(self.spec, self.policy)

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
        self._current_end = min(
            self._current_end,
            await self.reader.revalidate_locked(
                session, control, work, action, self.proof, now=await db_now(session)
            ),
        )
        self.validate_time(await db_now(session))

    def validate_time(self, now: datetime) -> None:
        self.require_composition()
        self.credential.require_time(now)
        from nexus.company.management.planning_native_facts import require_time

        require_time(self._current_end)
        super().validate_time(now)
