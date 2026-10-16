"""Genuine finite C witness around the actual source/context/native check; no DTO permission."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.context_store import PersistentContextAssembler
from nexus.company.management.coding_intent import CodingIntentCheck
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl, JournalAction


class NexusCodingModelIntentCheck(CodingIntentCheck):
    """Native router must require this same object before and after ModelIntentCheck."""

    def __init__(
        self, original: CodingIntentCheck, credential: AuthenticatedWorkerIdentity
    ) -> None:
        if (
            type(original) is not CodingIntentCheck
            or type(credential) is not AuthenticatedWorkerIdentity
        ):
            raise ValueError("Coding needs its actual original check and genuine C witness")
        original.require_composition()
        super().__init__(original._context_check, original._prepared, registry=original.registry)
        self.credential, self._original = credential, original
        self._witness_objects = (
            original,
            original._prepared,
            credential,
            self._context_check._revalidator,
        )
        self._witness_pins = self._witness_values()
        self.require_composition()

    @property
    def factory(self) -> async_sessionmaker[AsyncSession]:
        contexts = self._context_check._revalidator
        if type(contexts) is not PersistentContextAssembler:
            raise ValueError("Coding requires the original concrete context assembler")
        return contexts._factory

    def _witness_values(self) -> tuple[object, ...]:
        return (
            self.credential.identity,
            self.credential.issued_at,
            self.credential.expires_at,
            self.factory,
            self.fingerprint(),
        )

    def require_composition(self) -> None:
        super().require_composition()
        self._original.require_composition()
        check = self._context_check
        if (
            any(
                a is not b
                for a, b in zip(
                    self._witness_objects,
                    (self._original, self._original._prepared, self.credential, check._revalidator),
                    strict=True,
                )
            )
            or self._witness_values() != self._witness_pins
            or self._original._context_check is not check
            or self._original._prepared != self._prepared
            or check._identity != self.credential.identity
            or check._lease.expires_at > self.credential.expires_at
        ):
            raise ValueError("Coding original C credential/dependencies/window changed")

    def validate_time(self, now: datetime) -> None:
        self.require_composition()
        self.credential.require_time(now)
        manifest = self._prepared.context.manifest
        deadlines = (
            self._context_check._lease.expires_at,
            *(row.expires_at for row in manifest.contributors),
            *(row.fresh_until for row in manifest.source_heads),
        )
        if any(end is not None and now >= end for end in deadlines):
            raise ValueError("Coding original source/grant/lease window expired")

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        self.validate_time(now)
        await super().validate(session, control, work, action, now)
        self.validate_time(await db_now(session))
