"""Mandatory original-store proof around the genuine C context/native intent check."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.coding_prepared_contracts import StoredCodingRequest
from nexus.company.management.coding_prepared_store import CodingPreparedStore
from nexus.company.management.nexus_coding_model_intent import NexusCodingModelIntentCheck
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl, JournalAction


class StoredCodingIntent(NexusCodingModelIntentCheck):
    """Exact same Stored/Model/Stored object is required by the future closed C router.

    A header/marker or an actor/owner read is insufficient: the concrete store must
    have issued this very worker load with its genuine original witness and lease.
    """

    def __init__(
        self,
        original: NexusCodingModelIntentCheck,
        store: CodingPreparedStore,
        stored: StoredCodingRequest,
    ) -> None:
        if (
            type(original) is not NexusCodingModelIntentCheck
            or type(store) is not CodingPreparedStore
        ):
            raise ValueError("Coding requires its exact genuine check and concrete prepared store")
        original.require_composition()
        store.require_loaded(stored, original.credential, original._context_check._lease)
        if (
            original.factory is not store.factory
            or original._context_check._revalidator is not store.contexts
            or original._prepared != stored.prepared
        ):
            raise ValueError("Stored coding proof differs from original C context/factory/request")
        # Retain the genuine original wrapper rather than reconstructing a witness or seal.
        self.original, self.store, self.stored = original, store, stored
        self.credential, self._context_check, self._prepared = (
            original.credential,
            original._context_check,
            original._prepared,
        )
        self._registry = original.registry
        self._bound = (original, store, stored, original.credential, original._context_check)
        self._pins = original.fingerprint()
        self.require_composition()

    @property
    def factory(self) -> async_sessionmaker[AsyncSession]:
        return self.original.factory

    def require_composition(self) -> None:
        self.original.require_composition()
        self.store.require_composition()
        if (
            any(
                a is not b
                for a, b in zip(
                    self._bound,
                    (self.original, self.store, self.stored, self.credential, self._context_check),
                    strict=True,
                )
            )
            or self.original.fingerprint() != self._pins
            or self._prepared is not self.original._prepared
            or self._registry is not self.original.registry
            or self.factory is not self.store.factory
            or self._context_check._revalidator is not self.store.contexts
        ):
            raise ValueError("Original stored coding composition changed")
        self.store.require_loaded(self.stored, self.credential, self._context_check._lease)

    def validate_time(self, now: datetime) -> None:
        self.require_composition()
        self.original.validate_time(now)

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        self.validate_time(now)
        await self.original.validate(session, control, work, action, now)
        from nexus.execution.runtime_support import db_now

        await self.store.validate_loaded_locked(
            session,
            control,
            self.stored.prepared.scope,
            self.stored,
            self.credential,
            self._context_check._lease,
            now=await db_now(session),
        )
        await self.original.validate(session, control, work, action, await db_now(session))
        self.validate_time(await db_now(session))
