"""Opt-in credentialed managed dispatch retains native approval/source/recovery gates."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.notifications.delivery_contracts import SubmissionResult
from nexus.company.notifications.dispatch_store import NotificationTransportConfiguration
from nexus.company.notifications.draft_store import NotificationDraftStore
from nexus.company.notifications.ledger_rules import stable_idempotency_key
from nexus.company.notifications.managed_dispatch import ManagedNotificationDispatchStore
from nexus.company.notifications.managed_effects import ManagedNotificationEffectStore
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.notifications.worker_intent import (
    CredentialNotificationIntentCheck,
    require_credential_lease,
)
from nexus.company.notifications.worker_transport import CredentialedResendTransport
from nexus.execution.runtime_contracts import ExecutionLease


class AuthenticatedManagedNotificationDispatcher(ManagedNotificationDispatchStore):
    """Process-only credential composition; disabled default preserves existing dispatch APIs."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        drafts: NotificationDraftStore,
        effects: ManagedNotificationEffectStore,
        *,
        configuration: NotificationTransportConfiguration | None = None,
        enabled: bool = False,
    ) -> None:
        if type(enabled) is not bool:
            raise NotificationUnavailableError("Credentialed notification worker is disabled")
        self.worker_enabled = enabled
        super().__init__(factory, drafts, effects, configuration=configuration)

    async def dispatch(
        self, lease: ExecutionLease, identity: VerifiedIdentity, draft_id: UUID, action_id: UUID
    ) -> SubmissionResult | None:
        """A bare identity cannot skip this worker's actual credential verification path."""
        raise NotificationUnavailableError(
            "Credentialed notification dispatch requires its witness"
        )

    async def dispatch_with_credential(
        self,
        lease: ExecutionLease,
        witness: AuthenticatedWorkerIdentity,
        draft_id: UUID,
        action_id: UUID,
    ) -> SubmissionResult | None:
        """Expiry after commitment propagates; the native worker releases unknown capacity once."""
        async with asyncio.timeout(40):
            if self.worker_enabled is not True:
                raise NotificationUnavailableError("Credentialed notification worker is disabled")
            self.configuration.require_configured()
            require_credential_lease(lease, witness)
            identity = witness.identity
            if await self._existing(lease, identity, draft_id, action_id):
                return None
            witness.require_time(datetime.now(UTC))
            check = self._intent_check(lease, witness, draft_id, action_id)
            start = await self.effects.begin(lease, identity, action_id, before_intent=check)
            if not start.permit_external_call:
                return None
            result = await self._submit(check, action_id)
            receipt = self._receipt(start.record.proposal_hash, lease, action_id, result)
            await self.effects.record_receipt(lease, identity, receipt, actual_usd=None)
            await self._record(lease, identity, draft_id, receipt, result)
            return result

    def _intent_check(
        self,
        lease: ExecutionLease,
        witness: AuthenticatedWorkerIdentity,
        draft_id: UUID,
        action_id: UUID,
    ) -> CredentialNotificationIntentCheck:
        """Default native check; a final per-operation dispatcher can narrow its composition."""
        return CredentialNotificationIntentCheck(
            lease, witness, draft_id, self.drafts, self.target, self.resource_symbol
        )

    def _transport(self, check: CredentialNotificationIntentCheck) -> CredentialedResendTransport:
        """Construct the default transport before the same existing full native precall."""
        assert check.draft is not None
        return CredentialedResendTransport(
            check.draft.recipient_policy,
            self.configuration.api_key,
            check.witness,
            enabled=True,
            transport=self.configuration.http_transport,
        )

    async def _submit(
        self, check: CredentialNotificationIntentCheck, action_id: UUID
    ) -> SubmissionResult:
        assert check.draft is not None
        async with self._transport(check) as transport:
            await self._precall(check.lease, check.identity, check, action_id)
            check.validate_time(datetime.now(UTC))
            return await transport.submit(
                check.draft.payload,
                stable_idempotency_key(check.lease.company_id, check.draft_id),
            )
