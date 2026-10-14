"""Current authenticated owner native fact read with complete privacy and fresh final time."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_store import read_event
from nexus.company.brain.events import OutboxEvent
from nexus.company.brain.native_fact_contracts import NativeEventSelector, NativeFactProjection
from nexus.company.brain.native_fact_provenance import qualify_native_inputs
from nexus.company.brain.native_fact_resolution import resolve_fact
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.brain.native_fact_wake import event_selector, matches_event
from nexus.company.brain.scope_support import BrainDeniedError, require_brain_scope
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


class NativeFactReader:
    """Same-session descriptive current data; this produces no permit, lease or recipient."""

    def __init__(self, services: NativeFactServices) -> None:
        self.services = services

    async def load_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        selector: NativeEventSelector,
    ) -> NativeFactProjection | None:
        if (
            not session.in_transaction()
            or scope.task_id is not None
            or selector.company_id != scope.company_id
            or control.company_id != scope.company_id
            or self.services.catalog.company_id != scope.company_id
        ):
            raise BrainDeniedError("Native fact current owner scope is unavailable")
        await _actual_control(session, control, scope, identity)
        resolved = await resolve_fact(
            session, control, scope, identity, selector, self.services, await db_now(session)
        )
        if resolved is None:
            return None
        resources, deadlines = await qualify_native_inputs(
            session,
            control,
            scope,
            identity,
            self.services,
            resolved.resources,
            resolved.references,
        )
        await require_brain_scope(session, control, scope, identity, owner=True)
        final = await db_now(session)
        all_deadlines = tuple(sorted({*deadlines, *resolved.deadlines}))
        if any(value <= final for value in all_deadlines):
            raise BrainDeniedError("Native fact source/policy deadline expired")
        return NativeFactProjection(
            company_id=scope.company_id,
            selector=selector,
            state=resolved.state,
            resource=resolved.resource,
            required_resource_ids=resources,
            artifacts=resolved.references,
            protection_deadlines=all_deadlines,
            source_recorded_at=resolved.recorded_at,
        )

    async def load_event_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        event: OutboxEvent,
    ) -> NativeFactProjection | None:
        """Resolve an actual persisted wake; stale state cannot supply its own authority/hash."""
        await _actual_control(session, control, scope, identity)
        actual = await read_event(session, scope.company_id, event.event_id)
        if actual is None or actual != event:
            raise BrainDeniedError("Native event record is unavailable")
        selector = event_selector(actual, self.services)
        if selector is None:
            return None
        projection = await self.load_locked(session, control, scope, identity, selector)
        return projection if projection is not None and matches_event(actual, projection) else None


async def _actual_control(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
) -> None:
    """A transient/decoded control object cannot invent a native budget or owner snapshot."""
    actual = await session.scalar(
        select(CompanyControl)
        .where(CompanyControl.company_id == scope.company_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if actual is not control:
        raise BrainDeniedError("Native fact requires the actual locked company control row")
    await require_brain_scope(session, control, scope, identity, owner=True)
