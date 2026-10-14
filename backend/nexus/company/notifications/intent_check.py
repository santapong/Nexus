"""Actual EffectStore before-intent hook inserts a single deferred native dispatch slot."""

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.access_support import require_resources
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.generated_artifact_scope import action_expiry
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.dispatch_slots import reserve_notification_slot
from nexus.company.notifications.dispatch_support import (
    current_dispatch_draft,
    dispatch_scope,
    require_dispatch_time,
)
from nexus.company.notifications.dispatch_windows import require_dispatch_window
from nexus.company.notifications.draft_store import NotificationDraftStore
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.proposals import NotificationProposal
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl, JournalAction


class NotificationIntentCheck:
    def __init__(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        draft_id: UUID,
        drafts: NotificationDraftStore,
        target: ResourceRef,
        resource_symbol: str,
    ) -> None:
        self.lease, self.identity, self.draft_id, self.drafts = lease, identity, draft_id, drafts
        self.target, self.resource_symbol = target, resource_symbol
        self.draft: NotificationDraft | None = None
        self.day: object = None
        self.deadlines: tuple[datetime, ...] = ()

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        draft = await current_dispatch_draft(
            session, control, self.lease, self.identity, self.drafts, self.draft_id
        )
        proposal = ActionProposal.model_validate_json(action.proposal_json)
        NotificationProposal(
            company_id=work.company_id,
            draft_id=draft.draft_id,
            payload_sha256=draft.payload_sha256,
            recipient_policy_sha256=draft.recipient_policy.sha256,
            action=proposal,
        )
        if (
            proposal.tool_version != "v1"
            or proposal.resource != self.resource_symbol
            or (self.target.company_id != work.company_id or proposal.actor_id != control.owner_id)
        ):
            raise NotificationUnavailableError("Native notification target/action differs")
        previous = await session.get(NotificationDispatchRow, (work.company_id, draft.draft_id))
        if previous is not None:
            raise NotificationUnavailableError("Native notification already has a permanent intent")
        grants = await require_resources(
            session,
            dispatch_scope(self.lease, self.identity, action.id),
            (self.target.resource_id,),
            await db_now(session),
        )
        self.draft, self.deadlines = (
            draft,
            tuple(row.expires_at for row in grants if row.expires_at),
        )
        self.deadlines = (*self.deadlines, await action_expiry(session, action))
        await self._slot(session, work, action, await db_now(session))

    async def _slot(
        self, session: AsyncSession, work: ExecutionWork, action: JournalAction, now: datetime
    ) -> None:
        assert self.draft is not None
        self.day = await reserve_notification_slot(
            session, work, action, self.draft, self.drafts.policy, self.identity, now
        )
        self.validate_time(now)

    def validate_time(self, now: datetime) -> None:
        if self.draft is None or self.day != now.astimezone(ZoneInfo("Asia/Bangkok")).date():
            raise NotificationUnavailableError("Native notification issuance day changed")
        self.drafts.recipients.require_current(self.draft.recipient_policy, now)
        require_dispatch_window(self.draft, self.drafts.policy, now)
        require_dispatch_time(self.draft, self.lease, now)
        if any(value <= now for value in self.deadlines):
            raise NotificationUnavailableError("Native notification target access expired")
