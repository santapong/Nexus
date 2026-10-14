"""Actual native intent hook additionally retains a verified process credential window."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.notifications.draft_store import NotificationDraftStore
from nexus.company.notifications.intent_check import NotificationIntentCheck
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    WorkerIdentityDeniedError,
)
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl, JournalAction


def require_credential_lease(lease: ExecutionLease, witness: AuthenticatedWorkerIdentity) -> None:
    """Exact actor/workspace metadata only; current company/work permission stays native."""
    if not isinstance(witness, AuthenticatedWorkerIdentity) or (
        witness.identity.principal_id != lease.actor_id
        or witness.identity.workspace_id != lease.workspace_id
    ):
        raise WorkerIdentityDeniedError("Notification worker credential binding is unavailable")


class CredentialNotificationIntentCheck(NotificationIntentCheck):
    """A trusted per-operation check; neither witness nor token enters the durable command."""

    def __init__(
        self,
        lease: ExecutionLease,
        witness: AuthenticatedWorkerIdentity,
        draft_id: UUID,
        drafts: NotificationDraftStore,
        target: ResourceRef,
        resource_symbol: str,
    ) -> None:
        require_credential_lease(lease, witness)
        self.witness = witness
        super().__init__(lease, witness.identity, draft_id, drafts, target, resource_symbol)

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        action: JournalAction,
        now: datetime,
    ) -> None:
        """Keep actual source/approval/slot qualification and reject an expired credential."""
        require_credential_lease(self.lease, self.witness)
        self.witness.require_time(now)
        await super().validate(session, control, work, action, now)

    def validate_time(self, now: datetime) -> None:
        """The actual final intent-flush clock also closes the credential window."""
        require_credential_lease(self.lease, self.witness)
        self.witness.require_time(now)
        super().validate_time(now)
