"""Current owner qualified native drafts, same-session publication and source-safe reads."""

import asyncio
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.event_store import read_event
from nexus.company.brain.events import OutboxEvent
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.contracts import (
    NotificationDraft,
    NotificationPolicy,
    OwnerRecipientPolicy,
)
from nexus.company.notifications.draft_models import NotificationDraftRow
from nexus.company.notifications.draft_persistence import persist_draft_locked, stored_draft
from nexus.company.notifications.draft_store import (
    NotificationDraftStore,
    owner_scope,
    require_draft_time,
)
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.policy import trigger_sha256
from nexus.company.notifications.qualified_adapter import QualifiedNotificationFactAdapter
from nexus.company.notifications.qualified_contracts import DraftPublication
from nexus.company.notifications.qualified_facts import ObsoleteNotificationFactError
from nexus.company.notifications.qualified_obsolete import obsolete_publication_locked
from nexus.company.notifications.qualified_render import render_qualified_draft
from nexus.company.notifications.qualified_support import (
    qualify_saved_inputs_locked,
    require_draft_policy,
    require_owner_locked,
    require_protection_time,
    require_publication_scope,
    same_source,
)
from nexus.company.notifications.recipient_registry import RegisteredOwnerRecipients
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


class QualifiedNotificationDraftStore(NotificationDraftStore):
    loader: QualifiedNotificationFactAdapter

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        loader: QualifiedNotificationFactAdapter,
        recipients: RegisteredOwnerRecipients,
        *,
        policy: NotificationPolicy | None = None,
    ) -> None:
        super().__init__(factory, loader, recipients, policy=policy)

    async def publish_event(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, event_id: UUID
    ) -> NotificationDraft:
        """Compatible single-event body API; obsolete facts remain explicit unavailability."""
        result = await self.publish_event_result(scope, identity, event_id)
        if result.draft is None:
            raise ObsoleteNotificationFactError("Native notification wake is obsolete")
        return result.draft

    async def publish_event_result(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, event_id: UUID
    ) -> DraftPublication:
        async with asyncio.timeout(30):
            recipient = await self.prepare_recipient(scope, identity)
            async with management_owner_transaction(
                self.factory, scope, identity, allow_paused=True
            ) as (session, control, _):
                event = await read_event(session, scope.company_id, event_id)
                if event is None:
                    raise NotificationUnavailableError("Native notification event is unavailable")
                return await self.publish_locked(
                    session, control, scope, identity, event, recipient
                )

    async def prepare_recipient(
        self, scope: CompanyControlScope, identity: VerifiedIdentity
    ) -> OwnerRecipientPolicy:
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (session, control, _):
            if not self.policy.enabled:
                raise NotificationUnavailableError("Owner notifications are disabled")
            owner, now = control.owner_id, await db_now(session)
        recipient = await self.recipients.current(scope.company_id, owner, now)
        if recipient is None:
            raise NotificationUnavailableError("Owner recipient configuration is unavailable")
        return recipient

    async def publish_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        event: OutboxEvent,
        recipient: OwnerRecipientPolicy,
    ) -> DraftPublication:
        if not self.policy.enabled:
            raise NotificationUnavailableError("Owner notifications are disabled")
        await require_publication_scope(
            session, control, scope, identity, recipient, self.recipients
        )
        try:
            fact = await self.loader.load(
                session, control, owner_scope(scope, identity), identity, event
            )
        except ObsoleteNotificationFactError:
            return await obsolete_publication_locked(
                session,
                control,
                scope,
                identity,
                event,
                self.loader.reader.services,
                recipient,
                self.recipients,
            )
        draft = render_qualified_draft(scope, self.policy, recipient, fact, await db_now(session))
        existing = await session.scalar(
            select(NotificationDraftRow.draft_id).where(
                NotificationDraftRow.company_id == scope.company_id,
                NotificationDraftRow.trigger_sha256 == trigger_sha256(fact.signal),
            )
        )
        saved = await persist_draft_locked(session, draft, event.event_id)
        current = await self.get_current_locked(session, control, scope, identity, saved.draft_id)
        if current is None:
            raise NotificationUnavailableError("Qualified notification append is unavailable")
        same_source(draft, current)
        require_draft_time(current, await db_now(session))
        return DraftPublication(
            company_id=scope.company_id,
            event_id=event.event_id,
            state="coalesced" if existing else "published",
            reason="coalesced" if existing else "meaningful",
            draft=current,
        )

    async def get_current(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, draft_id: UUID
    ) -> NotificationDraft | None:
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (session, control, _):
            return await self.get_current_locked(session, control, scope, identity, draft_id)

    async def get_current_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        draft_id: UUID,
    ) -> NotificationDraft | None:
        await require_owner_locked(session, control, scope, identity)
        row = await session.get(NotificationDraftRow, (scope.company_id, draft_id))
        if row is None:
            return None
        saved = stored_draft(row)
        require_draft_policy(self.policy, saved)
        await require_publication_scope(
            session, control, scope, identity, saved.recipient_policy, self.recipients
        )
        event = await read_event(session, scope.company_id, saved.signal.event_ids[0])
        if event is None:
            raise NotificationUnavailableError("Native notification event is unavailable")
        try:
            fact = await self.loader.load(
                session, control, owner_scope(scope, identity), identity, event
            )
        except ObsoleteNotificationFactError:
            await self._obsolete_locked(session, control, scope, identity, saved)
            return None
        current = render_qualified_draft(
            scope, self.policy, saved.recipient_policy, fact, await db_now(session)
        )
        same_source(saved, current)
        await require_publication_scope(
            session, control, scope, identity, saved.recipient_policy, self.recipients
        )
        require_draft_time(saved, await db_now(session))
        return saved

    async def _obsolete_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        saved: NotificationDraft,
    ) -> None:
        deadlines = await qualify_saved_inputs_locked(
            session, control, scope, identity, self.loader.reader.services, saved
        )
        await require_publication_scope(
            session, control, scope, identity, saved.recipient_policy, self.recipients
        )
        now = await db_now(session)
        require_draft_time(saved, now)
        require_protection_time(deadlines, now)

    async def qualify_visited_batch_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        draft_ids: tuple[UUID, ...],
    ) -> tuple[datetime, ...]:
        """Re-license visible, obsolete and lookahead rows; returned deadlines confer no permit."""
        if len(draft_ids) > 32 or len(set(draft_ids)) != len(draft_ids):
            raise NotificationUnavailableError("Qualified notification batch exceeds its bound")
        await require_owner_locked(session, control, scope, identity)
        saved_rows: list[NotificationDraft] = []
        deadlines: set[datetime] = set()
        for draft_id in draft_ids:
            await self.get_current_locked(session, control, scope, identity, draft_id)
            row = await session.get(NotificationDraftRow, (scope.company_id, draft_id))
            if row is None:
                raise NotificationUnavailableError("Qualified notification visited row is missing")
            saved = stored_draft(row)
            saved_rows.append(saved)
            deadlines.update(
                await qualify_saved_inputs_locked(
                    session, control, scope, identity, self.loader.reader.services, saved
                )
            )
        for saved in saved_rows:
            await require_publication_scope(
                session, control, scope, identity, saved.recipient_policy, self.recipients
            )
        final = await db_now(session)
        for saved in saved_rows:
            require_draft_time(saved, final)
        ordered = tuple(sorted(deadlines))
        require_protection_time(ordered, final)
        return ordered

    async def qualify_current_batch_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        drafts: tuple[NotificationDraft, ...],
    ) -> None:
        """Qualify every collected source/recipient before any page body escapes."""
        if len(drafts) > 32:
            raise NotificationUnavailableError("Qualified notification batch exceeds its bound")
        await require_owner_locked(session, control, scope, identity)
        current = []
        for saved in drafts:
            found = await self.get_current_locked(session, control, scope, identity, saved.draft_id)
            if found is None or found != saved:
                raise NotificationUnavailableError("Qualified notification batch changed")
            current.append(found)
        for found in current:
            await require_publication_scope(
                session, control, scope, identity, found.recipient_policy, self.recipients
            )
        final = await db_now(session)
        for found in (*drafts, *current):
            require_draft_time(found, final)
