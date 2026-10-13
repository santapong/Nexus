"""Bounded true-owner reconciliation of issued facts, with no execution authority."""

from __future__ import annotations

import asyncio
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal
from nexus.execution.billing_contracts import (
    BillingEvidenceRecord,
    OwnerBillingLease,
    ReadOnlyBillingResolver,
)
from nexus.execution.effect_support import effect_record, effect_row
from nexus.execution.owner_billing_store import OwnerBillingStore
from nexus.execution.owner_reconcile_contracts import (
    OwnerReconciliationLease,
    ReadOnlyEvidenceResolver,
    ReconciliationRequest,
)
from nexus.execution.owner_reconcile_evidence import record_observation
from nexus.execution.owner_reconcile_support import owner_transaction, require_owner_lease
from nexus.execution.runtime_contracts import EffectRecord, ExecutionDeniedError, ExecutionSnapshot
from nexus.execution.runtime_recovery import release_locked
from nexus.execution.runtime_store import _lease, _ttl, _unresolved
from nexus.execution.runtime_support import db_now, mark_unknown_intents, snapshot
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import JournalAction

logger = structlog.get_logger()


class OwnerReconciliationStore:
    """No new attempts/effects/reservations; resolver is trusted nonserialized composition."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        resolver: ReadOnlyEvidenceResolver,
        *,
        timeout_seconds: int = 10,
        billing_resolver: ReadOnlyBillingResolver | None = None,
    ) -> None:
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 30:
            raise ValueError("Read-only resolution timeout must be 1..30 seconds")
        self._factory, self._resolver, self._timeout = factory, resolver, timeout_seconds
        self._billing_resolver = billing_resolver

    def _billing(self) -> OwnerBillingStore:
        if self._billing_resolver is None:
            raise ExecutionDeniedError("No trusted read-only billing resolver is configured")
        return OwnerBillingStore(self._factory, self._billing_resolver, self._timeout)

    async def claim_billing(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        task_id: UUID,
        worker_id: UUID,
        action_id: UUID,
        *,
        ttl_seconds: int = 60,
    ) -> OwnerBillingLease:
        """Acquire recording capacity only for the known receipt's unresolved historical bill."""
        return await self._billing().claim(
            scope, identity, task_id, worker_id, action_id, ttl_seconds=ttl_seconds
        )

    async def resolve_billing(
        self, owned: OwnerBillingLease, identity: VerifiedIdentity
    ) -> BillingEvidenceRecord | None:
        """Read and revalidate observed billing; never modify receipt or business state."""
        return await self._billing().resolve(owned, identity)

    async def renew_billing(
        self, owned: OwnerBillingLease, identity: VerifiedIdentity, *, ttl_seconds: int = 60
    ) -> OwnerBillingLease:
        return await self._billing().renew(owned, identity, ttl_seconds=ttl_seconds)

    async def release_billing(
        self, owned: OwnerBillingLease, identity: VerifiedIdentity
    ) -> ExecutionSnapshot:
        return await self._billing().release(owned, identity)

    async def claim(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        task_id: UUID,
        worker_id: UUID,
        *,
        ttl_seconds: int = 60,
    ) -> OwnerReconciliationLease:
        """Fence only expired/released issued work under the actual current owner."""
        duration = _ttl(ttl_seconds)
        async with owner_transaction(self._factory, scope, identity, task_id) as (session, row):
            now = await db_now(session)
            if row.worker_id is not None and row.lease_until is not None and row.lease_until > now:
                raise ExecutionDeniedError("Live execution lease cannot be taken over")
            unresolved = await _unresolved(session, row)
            if not unresolved or row.segment_id is None:
                raise ExecutionDeniedError(
                    "Owner reconciliation requires previously issued unresolved effects"
                )
            await mark_unknown_intents(session, row, unresolved)
            row.fence += 1
            row.worker_id, row.lease_until = worker_id, now + duration
            row.lease_mode, row.lease_principal_id, row.state = (
                "reconcile",
                scope.principal_id,
                "outcome_unknown",
            )
            await session.flush()
            return OwnerReconciliationLease(
                company_id=scope.company_id, execution=_lease(row), control_scope=scope
            )

    async def resolve(
        self, owned: OwnerReconciliationLease, identity: VerifiedIdentity, action_id: UUID
    ) -> EffectRecord | None:
        """Read bounded evidence outside the mutex, then recheck owner/fence before recording."""
        scope, lease = owned.control_scope, owned.execution
        request = await self._request(owned, identity, action_id)
        if isinstance(request, EffectRecord):
            return request
        try:
            observation = await asyncio.wait_for(
                self._resolver.resolve(request), timeout=self._timeout
            )
        except (TimeoutError, ValueError) as exc:
            logger.warning(
                "owner_evidence_lookup_unresolved",
                task_id=str(lease.task_id),
                trace_id=str(scope.trace_id),
                operation_id=str(scope.operation_id),
                error_type=type(exc).__name__,
            )
            return None
        async with owner_transaction(self._factory, scope, identity, lease.task_id) as (
            session,
            row,
        ):
            require_owner_lease(row, owned, await db_now(session))
            effect = await effect_row(session, row, action_id)
            if observation is None:
                return None
            return await record_observation(session, row, effect, owned, observation)

    async def _request(
        self, owned: OwnerReconciliationLease, identity: VerifiedIdentity, action_id: UUID
    ) -> ReconciliationRequest | EffectRecord:
        """Bind a read-only lookup to current owner and immutable original action/run."""
        scope, lease = owned.control_scope, owned.execution
        async with owner_transaction(self._factory, scope, identity, lease.task_id) as (
            session,
            row,
        ):
            require_owner_lease(row, owned, await db_now(session))
            effect = await effect_row(session, row, action_id)
            if effect.state in {"succeeded", "failed"}:
                return effect_record(effect)
            action = await session.get(JournalAction, action_id)
            if action is None:
                raise ExecutionDeniedError("Original action provenance is unavailable")
            proposal = ActionProposal.model_validate_json(action.proposal_json)
            if action_hash(proposal) != effect.proposal_hash or proposal.actor_id != row.actor_id:
                raise ExecutionDeniedError("Original action binding is inconsistent")
            return ReconciliationRequest(
                company_id=scope.company_id,
                lease=owned,
                proposal=proposal,
                effect=effect_record(effect),
            )

    async def renew(
        self, owned: OwnerReconciliationLease, identity: VerifiedIdentity, *, ttl_seconds: int = 60
    ) -> OwnerReconciliationLease:
        """Renew current owner recording capacity only, never actor execution authority."""
        async with owner_transaction(
            self._factory, owned.control_scope, identity, owned.execution.task_id
        ) as (session, row):
            now = await db_now(session)
            require_owner_lease(row, owned, now)
            row.lease_until = (
                max(row.lease_until, now + _ttl(ttl_seconds))
                if row.lease_until
                else now + _ttl(ttl_seconds)
            )
            await session.flush()
            return OwnerReconciliationLease(
                company_id=row.company_id, execution=_lease(row), control_scope=owned.control_scope
            )

    async def release(
        self, owned: OwnerReconciliationLease, identity: VerifiedIdentity
    ) -> ExecutionSnapshot:
        """Drop owner recording capacity while retaining receipts, quotas and unresolved holds."""
        async with owner_transaction(
            self._factory, owned.control_scope, identity, owned.execution.task_id
        ) as (session, row):
            require_owner_lease(row, owned, await db_now(session))
            await release_locked(session, row)
            return snapshot(row)
