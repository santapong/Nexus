"""Explicit missing native resolver/publisher boundaries; no default permissive implementation."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.delivery_contracts import SubmissionResult
from nexus.company.notifications.qualification import NotificationQualification
from nexus.execution.intent_checks import BeforeIntentCheck
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.harness.journal_models import CompanyControl


class NotificationSourceResolver(Protocol):
    """Configured native service loads actual events, sources, recipient policy and owner."""

    async def prepare(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, event_ids: tuple[UUID, ...]
    ) -> NotificationDraft:
        """Resolve native events and bounded protected bytes; never accept caller text/status."""
        ...

    async def revalidate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        draft: NotificationDraft,
        now: datetime,
    ) -> NotificationQualification:
        """Same CC-first txn, actual current source/policy/owner facts and full deadline set."""
        ...

    def before_intent(self, draft: NotificationDraft) -> BeforeIntentCheck:
        """Trusted exact persisted-draft/action/recipient/provenance gate plus final time check."""
        ...


class NotificationDispatch(Protocol):
    """Root integration must persist exact binding with M1 intent; no caller permit boolean."""

    async def dispatch(
        self, lease: ExecutionLease, identity: VerifiedIdentity, draft_id: UUID, action_id: UUID
    ) -> SubmissionResult:
        """Actual M1 begin/new permit only, one POST, persist known or unknown exact receipt."""
        ...
