"""Same-session native draft/link/cursor publication and final current source clock closure."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.event_store import BrainEventStore, read_event
from nexus.company.brain.events import EventCursor, OutboxEvent
from nexus.company.notifications.contracts import OwnerRecipientPolicy
from nexus.company.notifications.draft_store import owner_scope
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.qualified_contracts import DraftConsumption, DraftPublication
from nexus.company.notifications.qualified_obsolete import qualify_obsolete_event_locked
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.company.notifications.qualified_support import (
    require_protection_time,
    require_publication_scope,
)
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl

ACTIONABLE = frozenset(
    {
        "receipt_recorded",
        "verification_recorded",
        "decision_required",
        "work_blocked",
        "cap_exhausted",
        "digest_due",
    }
)


class QualifiedNotificationConsumer:
    def __init__(
        self, store: QualifiedNotificationDraftStore, *, consumer: str, recipe_version: str
    ) -> None:
        EventCursor(
            company_id=store.loader.catalog.company_id,
            consumer=consumer,
            recipe_version=recipe_version,
            last_sequence=0,
        )
        self.store, self.consumer, self.recipe_version = store, consumer, recipe_version

    async def consume(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, *, max_events: int = 32
    ) -> DraftConsumption:
        """An actionable failure exposes no body and rolls back the complete bounded batch."""
        async with asyncio.timeout(30):
            recipient = await self.store.prepare_recipient(scope, identity)
            handler = _QualifiedHandler(self.store, scope, identity, recipient)
            cursor = await BrainEventStore(self.store.factory).consume(
                owner_scope(scope, identity),
                identity,
                self.consumer,
                self.recipe_version,
                handler,
                max_events=max_events,
                finalizer=handler,
            )
            return DraftConsumption(
                company_id=scope.company_id, cursor=cursor, publications=tuple(handler.publications)
            )


class _QualifiedHandler:
    def __init__(
        self,
        store: QualifiedNotificationDraftStore,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        recipient: OwnerRecipientPolicy,
    ) -> None:
        self.store, self.scope, self.identity, self.recipient = store, scope, identity, recipient
        self.publications: list[DraftPublication] = []

    async def apply(self, session: AsyncSession, event: OutboxEvent) -> None:
        control = await self.control(session)
        if event.kind not in ACTIONABLE:
            self.publications.append(
                DraftPublication(
                    company_id=self.scope.company_id,
                    event_id=event.event_id,
                    state="ignored",
                    reason="unrelated_event",
                )
            )
            return
        result = await self.store.publish_locked(
            session, control, self.scope, self.identity, event, self.recipient
        )
        self.publications.append(result)

    async def control(self, session: AsyncSession) -> CompanyControl:
        control = await session.get(CompanyControl, self.scope.company_id)
        if control is None:
            raise NotificationUnavailableError(
                "Qualified notification actual control is unavailable"
            )
        return control

    async def finalize(self, session: AsyncSession) -> None:
        control = await self.control(session)
        drafts = tuple(row.draft for row in self.publications if row.draft is not None)
        await self.store.qualify_current_batch_locked(
            session, control, self.scope, self.identity, drafts
        )
        deadlines = {value for row in self.publications for value in row.protection_deadlines}
        for row in self.publications:
            if row.state != "obsolete":
                continue
            event = await read_event(session, self.scope.company_id, row.event_id)
            if event is None:
                raise NotificationUnavailableError("Native obsolete event is unavailable")
            deadlines.update(
                await qualify_obsolete_event_locked(
                    session,
                    control,
                    owner_scope(self.scope, self.identity),
                    self.identity,
                    event,
                    self.store.loader.reader.services,
                )
            )
        await require_publication_scope(
            session, control, self.scope, self.identity, self.recipient, self.store.recipients
        )
        final = await db_now(session)
        require_protection_time(tuple(deadlines), final)
        self.store.recipients.require_current(self.recipient, final)
        for draft in drafts:
            from nexus.company.notifications.draft_store import require_draft_time

            require_draft_time(draft, final)
