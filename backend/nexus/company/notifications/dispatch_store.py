"""Optional actual M1 owner dispatch; one committed permit, no resend or delivery inference."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid5

import httpx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceGeneration, ResourceRef
from nexus.company.brain.access_support import require_resources
from nexus.company.contracts.actions import ActionProposal
from nexus.company.contracts.results import ActionReceipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.notifications.delivery_contracts import SubmissionResult
from nexus.company.notifications.dispatch_contracts import NotificationProviderObservation
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.dispatch_support import (
    current_dispatch_draft,
    dispatch_scope,
    require_dispatch_time,
)
from nexus.company.notifications.draft_store import NotificationDraftStore
from nexus.company.notifications.intent_check import NotificationIntentCheck
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.observation_support import append_observation
from nexus.company.notifications.resend_transport import ResendTransport
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)


@dataclass(frozen=True)
class NotificationTransportConfiguration:
    enabled: bool = False
    api_key: SecretStr | None = None
    http_transport: httpx.MockTransport | None = None

    def require_configured(self) -> None:
        if (
            type(self.enabled) is not bool
            or not self.enabled
            or self.api_key is None
            or (
                not self.api_key.get_secret_value()
                or any(
                    ord(char) < 33 or ord(char) > 126 for char in self.api_key.get_secret_value()
                )
            )
        ):
            raise NotificationUnavailableError(
                "Owner notification transport is disabled/unconfigured"
            )


class NotificationDispatchStore:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        drafts: NotificationDraftStore,
        effects: EffectStore,
        target: ResourceRef,
        resource_symbol: str,
        *,
        configuration: NotificationTransportConfiguration | None = None,
    ) -> None:
        self.factory, self.drafts, self.effects = factory, drafts, effects
        self.target, self.resource_symbol = target, resource_symbol
        self.configuration = configuration or NotificationTransportConfiguration()

    async def dispatch(
        self, lease: ExecutionLease, identity: VerifiedIdentity, draft_id: UUID, action_id: UUID
    ) -> SubmissionResult | None:
        async with asyncio.timeout(40):
            self.configuration.require_configured()
            if await self._existing(lease, identity, draft_id, action_id):
                return None
            check = NotificationIntentCheck(
                lease, identity, draft_id, self.drafts, self.target, self.resource_symbol
            )
            start = await self.effects.begin(lease, identity, action_id, before_intent=check)
            if not start.permit_external_call:
                return None
            assert check.draft is not None
            await self._precall(lease, identity, check, action_id)
            check.validate_time(datetime.now(UTC))
            async with ResendTransport(
                check.draft.recipient_policy,
                self.configuration.api_key,
                enabled=True,
                transport=self.configuration.http_transport,
            ) as transport:
                from nexus.company.notifications.ledger_rules import stable_idempotency_key

                result = await transport.submit(
                    check.draft.payload, stable_idempotency_key(lease.company_id, draft_id)
                )
            receipt = self._receipt(start.record.proposal_hash, lease, action_id, result)
            await self.effects.record_receipt(lease, identity, receipt, actual_usd=None)
            await self._record(lease, identity, draft_id, receipt, result)
            return result

    async def _precall(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        check: NotificationIntentCheck,
        action_id: UUID,
    ) -> None:
        """Recheck real source/member/action after committed intent before touching HTTP."""
        from nexus.execution.effect_support import require_effect_authority

        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            work = await execution_row(session, lease_scope(lease))
            now = await db_now(session)
            require_lease(work, lease, now, execute=True)
            action = await require_effect_authority(
                session, control, work, action_id, now, (), lease_scope(lease), identity
            )
            intent = await session.get(EffectIntent, (lease.company_id, action_id))
            if intent is None or (intent.state, intent.intent_fence, intent.proposal_hash) != (
                "intent",
                lease.fence,
                action.proposal_hash,
            ):
                raise NotificationUnavailableError("Notification committed intent is unavailable")
            draft = await current_dispatch_draft(
                session, control, lease, identity, self.drafts, check.draft_id
            )
            if draft != check.draft:
                raise NotificationUnavailableError("Notification changed after intent commitment")
            grants = await self._target_grants(session, lease, identity, action_id)
            check.deadlines += tuple(row.expires_at for row in grants if row.expires_at)
            await self.effects.revalidate_execution_locked(
                session,
                control,
                work,
                identity,
                ActionProposal.model_validate_json(action.proposal_json),
                "tool_attempts",
            )
            final = await db_now(session)
            require_lease(work, lease, final, execute=True)
            check.validate_time(final)

    async def _target_grants(
        self,
        session: AsyncSession,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
    ) -> tuple[ResourceGeneration, ...]:
        if self.target.company_id != lease.company_id:
            raise NotificationUnavailableError("Notification target company differs")
        return await require_resources(
            session,
            dispatch_scope(lease, identity, action_id),
            (self.target.resource_id,),
            await db_now(session),
        )

    async def _existing(
        self, lease: ExecutionLease, identity: VerifiedIdentity, draft_id: UUID, action_id: UUID
    ) -> bool:
        async with runtime_transaction(
            self.factory, lease_scope(lease), identity, allow_paused=True, allow_inactive=True
        ) as (session, control, _):
            work = await execution_row(session, lease_scope(lease))
            require_lease(work, lease, await db_now(session))
            if lease.actor_id != control.owner_id or identity.principal_id != control.owner_id:
                raise NotificationUnavailableError("Only the actual current owner actor may notify")
            previous = await session.get(NotificationDispatchRow, (lease.company_id, draft_id))
            intent = await session.get(EffectIntent, (lease.company_id, action_id))
            if previous is not None and (
                previous.action_id,
                previous.task_id,
                previous.trace_id,
                previous.run_id,
            ) != (action_id, lease.task_id, lease.trace_id, lease.run_id):
                raise NotificationUnavailableError(
                    "Notification draft already binds another native intent"
                )
            return previous is not None or intent is not None

    def _receipt(
        self, proposal_hash: str, lease: ExecutionLease, action_id: UUID, result: SubmissionResult
    ) -> ActionReceipt:
        return ActionReceipt(
            company_id=lease.company_id,
            receipt_id=uuid5(action_id, "notification-submission-v1"),
            action_id=action_id,
            task_id=lease.task_id,
            trace_id=lease.trace_id,
            proposal_hash=proposal_hash,
            outcome="succeeded"
            if result.outcome == "accepted"
            else "failed"
            if result.outcome in {"rejected", "blocked"}
            else "outcome_unknown",
            recorded_at=datetime.now(UTC),
            external_id=str(result.provider_id) if result.provider_id else None,
        )

    async def _record(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        draft_id: UUID,
        receipt: ActionReceipt,
        result: SubmissionResult,
    ) -> None:
        async with runtime_transaction(
            self.factory, lease_scope(lease), identity, allow_paused=True, allow_inactive=True
        ) as (session, control, _):
            intent = await session.get(EffectIntent, (lease.company_id, receipt.action_id))
            if intent is None or intent.receipt_json != receipt.model_dump_json():
                raise NotificationUnavailableError(
                    "Provider evidence needs its exact actual M1 receipt"
                )
            draft = await current_dispatch_draft(
                session, control, lease, identity, self.drafts, draft_id
            )
            value = NotificationProviderObservation(
                company_id=lease.company_id,
                observation_id=uuid5(receipt.action_id, "notification-submission-v1"),
                draft_id=draft_id,
                action_id=receipt.action_id,
                payload_sha256=draft.payload_sha256,
                kind="submission",
                submission=result,
                receipt_id=receipt.receipt_id,
                receipt_sha256=canonical_sha256(receipt),
                recorded_by=identity.principal_id,
                operation_id=receipt.action_id,
                audit_trace_id=lease.trace_id,
                observed_at=receipt.recorded_at,
            )
            await append_observation(session, value)
            self.drafts.recipients.require_current(draft.recipient_policy, await db_now(session))
            require_dispatch_time(draft, lease, await db_now(session))
