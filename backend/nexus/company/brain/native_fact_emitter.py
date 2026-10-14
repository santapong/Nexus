"""Same-company native fact wake append/replay; no receipt, cost or execution publication."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_store import append_event
from nexus.company.brain.events import OutboxEvent
from nexus.company.brain.native_fact_contracts import NativeEventSelector
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.native_fact_wake import wake_key, wake_pins
from nexus.company.brain.scope_support import BrainDeniedError, brain_transaction
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


class NativeFactEmitter:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        reader: NativeFactReader,
        *,
        operation_guard: NotificationOperationGuard | None = None,
    ) -> None:
        if operation_guard is not None and not isinstance(
            operation_guard, NotificationOperationGuard
        ):
            raise ValueError("Native notification operation guard is unavailable")
        self.factory, self.reader, self.operation_guard = factory, reader, operation_guard

    async def emit(
        self,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        selector: NativeEventSelector,
    ) -> OutboxEvent | None:
        if self.operation_guard is not None:
            self.operation_guard.require_identity(identity)
            self.operation_guard.require_company(scope.company_id)
            self.operation_guard.require_company(selector.company_id)
        async with brain_transaction(self.factory, scope, identity, owner=True) as (
            session,
            control,
            _,
        ):
            return await self.emit_locked(session, control, scope, identity, selector)

    async def emit_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        selector: NativeEventSelector,
    ) -> OutboxEvent | None:
        if self.operation_guard is not None:
            self.operation_guard.require_identity(identity)
            self.operation_guard.require_company(scope.company_id)
            self.operation_guard.require_company(control.company_id)
            self.operation_guard.require_company(selector.company_id)
            self.operation_guard.require_company(self.reader.services.catalog.company_id)
        fact = await self.reader.load_locked(session, control, scope, identity, selector)
        if fact is None:
            if self.operation_guard is not None:
                self.operation_guard.require_time(await db_now(session))
            return None
        event = await append_event(
            session,
            scope,
            kind=selector.kind,
            resource_id=fact.resource.resource_id,
            deduplication_key=wake_key(fact),
            now=await db_now(session),
            **wake_pins(fact),
        )
        current = await self.reader.load_locked(session, control, scope, identity, selector)
        if current is None or (
            current.state_sha256,
            current.resource,
            current.required_resource_ids,
            current.artifacts,
        ) != (fact.state_sha256, fact.resource, fact.required_resource_ids, fact.artifacts):
            raise BrainDeniedError("Native wake source state changed before final publication")
        final = await db_now(session)
        if any(
            value <= final for value in (*fact.protection_deadlines, *current.protection_deadlines)
        ):
            raise BrainDeniedError("Native wake input protection expired after publication")
        if self.operation_guard is not None:
            self.operation_guard.require_time(final)
        return event
