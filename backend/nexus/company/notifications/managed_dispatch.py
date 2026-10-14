"""Current managed sender rederivation after committed intent, before the one-call adapter."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.company.notifications.dispatch_store import (
    NotificationDispatchStore,
    NotificationTransportConfiguration,
)
from nexus.company.notifications.dispatch_support import dispatch_scope
from nexus.company.notifications.draft_store import NotificationDraftStore
from nexus.company.notifications.intent_check import NotificationIntentCheck
from nexus.company.notifications.managed_effects import ManagedNotificationEffectStore
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.execution.effect_support import require_effect_authority
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    runtime_transaction,
)


class ManagedNotificationDispatchStore(NotificationDispatchStore):
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        drafts: NotificationDraftStore,
        effects: ManagedNotificationEffectStore,
        *,
        configuration: NotificationTransportConfiguration | None = None,
    ) -> None:
        self.managed_effects = effects
        policy = effects.preparation.policy
        super().__init__(
            factory,
            drafts,
            effects,
            policy.target,
            policy.resource_symbol,
            configuration=configuration,
        )

    async def _precall(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        check: NotificationIntentCheck,
        action_id: UUID,
    ) -> None:
        await super()._precall(lease, identity, check, action_id)
        async with runtime_transaction(self.factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            work = await execution_row(session, lease_scope(lease))
            action = await require_effect_authority(
                session,
                control,
                work,
                action_id,
                await db_now(session),
                (),
                lease_scope(lease),
                identity,
            )
            current = await self.managed_effects.preparation.admit(
                session,
                control,
                dispatch_scope(lease, identity, action_id),
                identity,
                work,
                check.draft_id,
                ActionProposal.model_validate_json(action.proposal_json),
            )
            intent = await session.get(EffectIntent, (lease.company_id, action_id))
            if intent is None or (intent.state, intent.intent_fence, intent.proposal_hash) != (
                "intent",
                lease.fence,
                action.proposal_hash,
            ):
                raise NotificationUnavailableError("Managed notification intent is unavailable")
            if current.draft != check.draft:
                raise NotificationUnavailableError("Managed notification changed after intent")
            check.deadlines += current.deadlines
            final = await db_now(session)
            require_lease(work, lease, final, execute=True)
            current.require_time(self.managed_effects.preparation.catalog, final)
            check.validate_time(final)
