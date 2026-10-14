"""Exact existing owner actor, immutable draft and current source qualification under CC."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.event_store import read_event
from nexus.company.brain.scope_support import require_brain_scope
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.draft_models import NotificationDraftRow
from nexus.company.notifications.draft_persistence import stored_draft
from nexus.company.notifications.draft_store import NotificationDraftStore, require_draft_time
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


def dispatch_scope(
    lease: ExecutionLease, identity: VerifiedIdentity, operation: UUID
) -> BrainReadScope:
    return BrainReadScope(
        company_id=lease.company_id,
        workspace_id=lease.workspace_id,
        principal_id=identity.principal_id,
        operation_id=operation,
        trace_id=lease.trace_id,
    )


async def current_dispatch_draft(
    session: AsyncSession,
    control: CompanyControl,
    lease: ExecutionLease,
    identity: VerifiedIdentity,
    drafts: NotificationDraftStore,
    draft_id: UUID,
) -> NotificationDraft:
    if lease.actor_id != control.owner_id or identity.principal_id != control.owner_id:
        raise NotificationUnavailableError("Only the actual current owner actor may notify")
    scope = dispatch_scope(lease, identity, draft_id)
    await require_brain_scope(session, control, scope, identity, owner=True)
    row = await session.get(NotificationDraftRow, (lease.company_id, draft_id))
    if row is None:
        raise NotificationUnavailableError("Native notification draft is unavailable")
    saved = stored_draft(row)
    event = await read_event(session, lease.company_id, saved.signal.event_ids[0])
    if event is None:
        raise NotificationUnavailableError("Native notification event is unavailable")
    fact = await drafts.loader.load(session, control, scope, identity, event)
    if fact.provenance != saved.provenance or fact.signal.state_sha256 != saved.signal.state_sha256:
        raise NotificationUnavailableError("Native notification source snapshot changed")
    drafts.recipients.require_current(saved.recipient_policy, await db_now(session))
    require_draft_time(saved, await db_now(session))
    return saved


def require_dispatch_time(draft: NotificationDraft, lease: ExecutionLease, now: datetime) -> None:
    require_draft_time(draft, now)
    if lease.expires_at <= now:
        raise NotificationUnavailableError("Native notification execute lease expired")
