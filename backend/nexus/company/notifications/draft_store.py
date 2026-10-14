"""Current signed-owner native event/draft publication; no M1 permit, send or cursor claim."""

import asyncio
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_models import BrainEvent
from nexus.company.brain.event_store import event_record
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.contracts import (
    NotificationDraft,
    NotificationPolicy,
    OwnerRecipientPolicy,
)
from nexus.company.notifications.draft_models import NotificationDraftRow
from nexus.company.notifications.draft_persistence import persist_draft_locked, stored_draft
from nexus.company.notifications.native_facts import (
    NativeNotificationFact,
    NotificationUnavailableError,
    render_native_draft,
)
from nexus.company.notifications.native_loader import NativeNotificationFactLoader
from nexus.company.notifications.recipient_registry import RegisteredOwnerRecipients
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


def owner_scope(scope: CompanyControlScope, identity: VerifiedIdentity) -> BrainReadScope:
    return BrainReadScope(
        company_id=scope.company_id,
        workspace_id=identity.workspace_id,
        principal_id=scope.principal_id,
        operation_id=scope.operation_id,
        trace_id=scope.trace_id,
    )


def require_draft_time(draft: NotificationDraft, now: datetime) -> None:
    if not draft.recipient_policy.registered_at <= now < draft.recipient_policy.expires_at or any(
        value <= now for value in draft.provenance.protection_deadlines
    ):
        raise NotificationUnavailableError("Native notification qualification expired")


class NotificationDraftStore:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        loader: NativeNotificationFactLoader,
        recipients: RegisteredOwnerRecipients,
        *,
        policy: NotificationPolicy | None = None,
    ) -> None:
        self.factory, self.loader, self.recipients, self.policy = (
            factory,
            loader,
            recipients,
            policy or NotificationPolicy(),
        )

    async def publish_event(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, event_id: UUID
    ) -> NotificationDraft:
        async with asyncio.timeout(30):
            fact, recipient = await self._prepare(scope, identity, event_id)
            async with management_owner_transaction(
                self.factory, scope, identity, allow_paused=True
            ) as (session, control, _):
                current = await self._fact(session, control, scope, identity, event_id)
                if canonical_sha256(current) != canonical_sha256(fact):
                    raise NotificationUnavailableError(
                        "Native notification changed during preparation"
                    )
                now = await db_now(session)
                if recipient is None or recipient.owner_id != control.owner_id:
                    raise NotificationUnavailableError(
                        "Owner recipient configuration is unavailable"
                    )
                self.recipients.require_current(recipient, now)
                prepared = render_native_draft(scope, self.policy, recipient, current, now)
                saved = await self._persist(session, prepared, event_id)
                await self._final(session, control, scope, identity, saved)
                return saved

    async def get_current(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, draft_id: UUID
    ) -> NotificationDraft | None:
        async with asyncio.timeout(30):
            async with management_owner_transaction(
                self.factory, scope, identity, allow_paused=True
            ) as (session, control, _):
                row = await session.get(NotificationDraftRow, (scope.company_id, draft_id))
                if row is None:
                    return None
                saved = stored_draft(row)
                current = await self._fact(
                    session, control, scope, identity, saved.signal.event_ids[0]
                )
                if current.provenance != saved.provenance or (
                    current.signal.state_sha256 != saved.signal.state_sha256
                ):
                    raise NotificationUnavailableError(
                        "Native notification snapshot is unavailable"
                    )
                await self._final(session, control, scope, identity, saved)
                return saved

    async def _prepare(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, event_id: UUID
    ) -> tuple[NativeNotificationFact, OwnerRecipientPolicy | None]:
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (session, control, _):
            if not self.policy.enabled:
                raise NotificationUnavailableError("Owner notifications are disabled")
            fact = await self._fact(session, control, scope, identity, event_id)
            owner = control.owner_id
            now = await db_now(session)
        recipient = await self.recipients.current(scope.company_id, owner, now)
        return fact, recipient

    async def _fact(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        event_id: UUID,
    ) -> NativeNotificationFact:
        row = await session.get(BrainEvent, (scope.company_id, event_id))
        if row is None:
            raise NotificationUnavailableError("Native notification event is unavailable")
        return await self.loader.load(
            session, control, owner_scope(scope, identity), identity, event_record(row)
        )

    async def _persist(
        self, session: AsyncSession, prepared: NotificationDraft, event_id: UUID
    ) -> NotificationDraft:
        return await persist_draft_locked(session, prepared, event_id)

    async def _final(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        saved: NotificationDraft,
    ) -> None:
        await require_brain_scope(
            session, control, owner_scope(scope, identity), identity, owner=True
        )
        self.recipients.require_current(saved.recipient_policy, await db_now(session))
        require_draft_time(saved, await db_now(session))
