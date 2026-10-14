"""Current owner bounded inbox reads hold one company mutex and hide the entire failed page."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.contracts import OwnerRecipientPolicy
from nexus.company.notifications.draft_models import NotificationDraftRow
from nexus.company.notifications.draft_store import require_draft_time
from nexus.company.notifications.inbox_contracts import (
    MAX_INBOX_BYTES,
    InboxUnavailableError,
    NotificationInboxEntry,
    NotificationInboxPage,
)
from nexus.company.notifications.inbox_observations import inbox_entry
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


def validate_inbox_limit(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 8:
        raise ValueError("Inbox limit must be an integer from1to8")
    return value


@dataclass(frozen=True)
class InboxMetadataPage:
    rendered_ids: tuple[UUID, ...]
    licensed_ids: tuple[UUID, ...]
    next_after_id: UUID | None


class NotificationInboxStore:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        drafts: QualifiedNotificationDraftStore,
    ) -> None:
        self.factory, self.drafts = factory, drafts

    async def current_page(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        *,
        after_id: UUID | None = None,
        limit: int = 4,
    ) -> NotificationInboxPage:
        limit = validate_inbox_limit(limit)
        async with (
            asyncio.timeout(30),
            management_owner_transaction(self.factory, scope, identity, allow_paused=True) as (
                session,
                control,
                _,
            ),
        ):
            metadata = await page_ids(session, control, scope, after_id, limit)
            entries = []
            for draft_id in metadata.rendered_ids:
                entry = await self._entry(session, control, scope, identity, draft_id)
                if entry is not None:
                    entries.append(entry)
            checked_at = await self._final(
                session, control, scope, identity, tuple(entries), metadata.licensed_ids
            )
            page = NotificationInboxPage(
                company_id=scope.company_id,
                checked_at=checked_at,
                notifications=tuple(entries),
                next_after_id=metadata.next_after_id,
            )
            require_inbox_size(page)
            return page

    async def current(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, draft_id: UUID
    ) -> NotificationInboxEntry | None:
        async with (
            asyncio.timeout(30),
            management_owner_transaction(self.factory, scope, identity, allow_paused=True) as (
                session,
                control,
                _,
            ),
        ):
            saved = await self.drafts.get_current_locked(
                session, control, scope, identity, draft_id
            )
            if saved is None:
                return None
            entry = await inbox_entry(session, saved)
            await self._final(session, control, scope, identity, (entry,), (draft_id,))
            require_inbox_size(entry)
            return entry

    async def _entry(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        draft_id: UUID,
    ) -> NotificationInboxEntry | None:
        saved = await self.drafts.get_current_locked(session, control, scope, identity, draft_id)
        if saved is None:
            return None
        return await inbox_entry(session, saved)

    async def _final(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        entries: tuple[NotificationInboxEntry, ...],
        visited_ids: tuple[UUID, ...],
    ) -> datetime:
        drafts = tuple(entry.draft for entry in entries)
        deadlines = await self.drafts.qualify_visited_batch_locked(
            session, control, scope, identity, visited_ids
        )
        await self.drafts.qualify_current_batch_locked(session, control, scope, identity, drafts)
        recipients = await recipient_pins(session, control, scope, visited_ids)
        now = await db_now(session)
        if any(value <= now for value in deadlines):
            raise InboxUnavailableError("Notification unavailable")
        for recipient in recipients:
            self.drafts.recipients.require_current(recipient, now)
        for draft in drafts:
            require_draft_time(draft, now)
        return now


async def recipient_pins(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    visited_ids: tuple[UUID, ...],
) -> tuple[OwnerRecipientPolicy, ...]:
    """Only immutable pins from barrier-qualified rows; no body or permission is inferred."""
    if not visited_ids:
        return ()
    rows = tuple(
        (
            await session.scalars(
                select(NotificationDraftRow.recipient_policy_json).where(
                    NotificationDraftRow.company_id == scope.company_id,
                    NotificationDraftRow.recipient_owner_id == control.owner_id,
                    NotificationDraftRow.draft_id.in_(visited_ids),
                )
            )
        ).all()
    )
    if len(rows) != len(visited_ids):
        raise InboxUnavailableError("Notification unavailable")
    return tuple(OwnerRecipientPolicy.model_validate_json(row) for row in rows)


async def page_ids(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    after_id: UUID | None,
    limit: int,
) -> InboxMetadataPage:
    where = (
        NotificationDraftRow.company_id == scope.company_id,
        NotificationDraftRow.recipient_owner_id == control.owner_id,
    )
    query = select(NotificationDraftRow.draft_id).where(*where)
    if after_id is not None:
        cursor = (
            await session.execute(
                select(NotificationDraftRow.recorded_at, NotificationDraftRow.draft_id).where(
                    *where, NotificationDraftRow.draft_id == after_id
                )
            )
        ).one_or_none()
        if cursor is None:
            raise InboxUnavailableError("Notification cursor unavailable")
        query = query.where(
            or_(
                NotificationDraftRow.recorded_at < cursor.recorded_at,
                and_(
                    NotificationDraftRow.recorded_at == cursor.recorded_at,
                    NotificationDraftRow.draft_id < cursor.draft_id,
                ),
            )
        )
    query_limit = min(limit + 1, 8) if after_id is not None else limit + 1
    ids = tuple(
        (
            await session.scalars(
                query.order_by(
                    NotificationDraftRow.recorded_at.desc(), NotificationDraftRow.draft_id.desc()
                ).limit(query_limit)
            )
        ).all()
    )
    return metadata_page(ids, after_id, limit)


def metadata_page(ids: tuple[UUID, ...], after_id: UUID | None, limit: int) -> InboxMetadataPage:
    """A full cursor+limit8 scan may have a next cursor leading to an empty licensed page."""
    visited = (*((after_id,) if after_id is not None else ()), *ids)
    if len(visited) > 9:
        raise InboxUnavailableError("Notification unavailable")
    next_possible = len(ids) > limit or (after_id is not None and limit == 8 and len(ids) == 8)
    return InboxMetadataPage(
        rendered_ids=ids[:limit],
        licensed_ids=visited,
        next_after_id=ids[limit - 1] if next_possible else None,
    )


def require_inbox_size(value: NotificationInboxPage | NotificationInboxEntry) -> None:
    if len(value.model_dump_json().encode()) > MAX_INBOX_BYTES:
        raise InboxUnavailableError("Notification unavailable")
