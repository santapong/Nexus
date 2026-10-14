"""Explicit private owner status polling; provider acceptance/delivery/billing stay separate."""

import asyncio
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceGeneration, ResourceRef
from nexus.company.brain.access_support import require_resources
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.contracts import NotificationDraft
from nexus.company.notifications.delivery_contracts import StatusResult, SubmissionResult
from nexus.company.notifications.dispatch_contracts import NotificationProviderObservation
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.dispatch_store import NotificationTransportConfiguration
from nexus.company.notifications.draft_store import (
    NotificationDraftStore,
    owner_scope,
    require_draft_time,
)
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.observation_support import append_observation, observation_id
from nexus.company.notifications.resend_transport import ResendTransport
from nexus.company.notifications.status_support import current_owner_message, known_message
from nexus.execution.runtime_support import db_now


class NotificationStatusStore:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        drafts: NotificationDraftStore,
        *,
        target: ResourceRef | None = None,
        configuration: NotificationTransportConfiguration | None = None,
    ) -> None:
        self.factory, self.drafts = factory, drafts
        self.configuration = configuration or NotificationTransportConfiguration()
        self.target = target

    async def poll(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, draft_id: UUID
    ) -> NotificationProviderObservation | None:
        async with asyncio.timeout(30):
            self.configuration.require_configured()
            before = await self._prepare(scope, identity, draft_id)
            if before is None:
                return None
            draft, _, receipt = before
            assert receipt.external_id is not None
            async with ResendTransport(
                draft.recipient_policy,
                self.configuration.api_key,
                enabled=True,
                transport=self.configuration.http_transport,
            ) as transport:
                result = await transport.retrieve(draft.payload, UUID(receipt.external_id))
            return await self._observe(scope, identity, draft, receipt, result)

    async def reconcile_known(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, draft_id: UUID
    ) -> NotificationProviderObservation | None:
        """Append proof for a known native receipt; unknown/noID remains unresolved without GET."""
        async with asyncio.timeout(40):
            return await self._reconcile_known(scope, identity, draft_id)

    async def _reconcile_known(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, draft_id: UUID
    ) -> NotificationProviderObservation | None:
        observed = await self.poll(scope, identity, draft_id)
        if observed is None or observed.status is None or observed.status.outcome != "observed":
            return None
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (session, control, _):
            draft = await current_owner_message(
                session, control, scope, identity, self.drafts, draft_id
            )
            known = await known_message(session, scope, draft_id)
            if known is None or known[1].receipt_id != observed.receipt_id:
                raise NotificationUnavailableError(
                    "Native notification receipt changed during reconciliation"
                )
            receipt = known[1]
            value = NotificationProviderObservation(
                company_id=scope.company_id,
                observation_id=observation_id(
                    receipt, "reconciliation", observed.status.response_sha256
                ),
                draft_id=draft_id,
                action_id=receipt.action_id,
                payload_sha256=draft.payload_sha256,
                kind="reconciliation",
                submission=SubmissionResult(
                    outcome="accepted",
                    reason="accepted",
                    provider_id=observed.status.provider_id,
                    response_sha256=observed.status.response_sha256,
                ),
                receipt_id=receipt.receipt_id,
                receipt_sha256=canonical_sha256(receipt),
                recorded_by=identity.principal_id,
                operation_id=scope.operation_id,
                audit_trace_id=scope.trace_id,
                observed_at=await db_now(session),
            )
            value = await append_observation(session, value)
            grants = await self._target(session, scope, identity)
            self.drafts.recipients.require_current(draft.recipient_policy, await db_now(session))
            require_status_time(draft, grants, await db_now(session))
            return value

    async def _prepare(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, draft_id: UUID
    ) -> tuple[NotificationDraft, NotificationDispatchRow, ActionReceipt] | None:
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (session, control, _):
            draft = await current_owner_message(
                session, control, scope, identity, self.drafts, draft_id
            )
            known = await known_message(session, scope, draft_id)
            if known is None:
                return None
            await self._target(session, scope, identity)
            return draft, known[0], known[1]

    async def _target(
        self, session: AsyncSession, scope: CompanyControlScope, identity: VerifiedIdentity
    ) -> tuple[ResourceGeneration, ...]:
        if self.target is None or self.target.company_id != scope.company_id:
            raise NotificationUnavailableError("Notification target is unconfigured")
        return await require_resources(
            session, owner_scope(scope, identity), (self.target.resource_id,), await db_now(session)
        )

    async def _observe(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        draft: NotificationDraft,
        receipt: ActionReceipt,
        result: StatusResult,
    ) -> NotificationProviderObservation:
        draft_id = draft.draft_id

        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (
            session,
            control,
            _,
        ):
            current = await current_owner_message(
                session, control, scope, identity, self.drafts, draft_id
            )
            known = await known_message(session, scope, draft_id)
            if known is None or known[1] != receipt or current != draft:
                raise NotificationUnavailableError(
                    "Native notification changed during status lookup"
                )
            value = NotificationProviderObservation(
                company_id=scope.company_id,
                observation_id=observation_id(receipt, "delivery", result.response_sha256),
                draft_id=draft_id,
                action_id=receipt.action_id,
                payload_sha256=draft.payload_sha256,
                kind="delivery",
                status=result,
                receipt_id=receipt.receipt_id,
                receipt_sha256=canonical_sha256(receipt),
                recorded_by=identity.principal_id,
                operation_id=scope.operation_id,
                audit_trace_id=scope.trace_id,
                observed_at=await db_now(session),
            )
            value = await append_observation(session, value)
            grants = await self._target(session, scope, identity)
            self.drafts.recipients.require_current(draft.recipient_policy, await db_now(session))
            final = await db_now(session)
            require_status_time(draft, grants, final)
            return value


def require_status_time(
    draft: NotificationDraft, grants: tuple[ResourceGeneration, ...], now: datetime
) -> None:
    require_draft_time(draft, now)
    if any(row.expires_at is not None and row.expires_at <= now for row in grants):
        raise NotificationUnavailableError("Notification target access expired")
