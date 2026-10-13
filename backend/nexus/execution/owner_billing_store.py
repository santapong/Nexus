"""Billing-only current-owner continuation; known receipts and business states never change."""

from __future__ import annotations

import asyncio
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.execution.billing_contracts import (
    BillingEvidenceRecord,
    BillingLookupRequest,
    BillingObservation,
    OwnerBillingLease,
    ReadOnlyBillingResolver,
    receipt_digest,
)
from nexus.execution.billing_support import billing_request, known_billing, require_observation
from nexus.execution.owner_billing_write import record_bill
from nexus.execution.owner_reconcile_support import owner_transaction, require_owner_lease
from nexus.execution.runtime_contracts import ExecutionDeniedError, ExecutionSnapshot
from nexus.execution.runtime_store import _lease, _ttl
from nexus.execution.runtime_support import db_now, snapshot

logger = structlog.get_logger()


class OwnerBillingStore:
    """Only already issued known outcomes with unknown billing can enter this recording path."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        resolver: ReadOnlyBillingResolver,
        timeout_seconds: int,
    ) -> None:
        self._factory, self._resolver, self._timeout = factory, resolver, timeout_seconds

    async def claim(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        task_id: UUID,
        worker_id: UUID,
        action_id: UUID,
        *,
        ttl_seconds: int = 60,
    ) -> OwnerBillingLease:
        duration = _ttl(ttl_seconds)
        async with owner_transaction(self._factory, scope, identity, task_id) as (session, row):
            now = await db_now(session)
            if row.worker_id is not None and row.lease_until is not None and row.lease_until > now:
                raise ExecutionDeniedError("Live execution lease cannot be taken over for billing")
            effect, _, hold, receipt = await known_billing(session, row, action_id)
            if hold.state not in {"held", "unknown"} or row.segment_id is None:
                raise ExecutionDeniedError(
                    "Billing continuation requires an unresolved issued bill"
                )
            row.fence += 1
            row.worker_id, row.lease_until = worker_id, now + duration
            row.lease_mode, row.lease_principal_id = "reconcile", scope.principal_id
            assert effect.receipt_json is not None
            await session.flush()
            return OwnerBillingLease(
                company_id=row.company_id,
                execution=_lease(row),
                control_scope=scope,
                action_id=action_id,
                receipt_id=receipt.receipt_id,
                receipt_hash=receipt_digest(effect.receipt_json),
            )

    async def resolve(
        self, owned: OwnerBillingLease, identity: VerifiedIdentity
    ) -> BillingEvidenceRecord | None:
        request = await self._request(owned, identity)
        try:
            observation = await asyncio.wait_for(
                self._resolver.resolve(request), timeout=self._timeout
            )
        except (TimeoutError, ValueError) as exc:
            logger.warning(
                "owner_billing_lookup_unknown",
                task_id=str(owned.execution.task_id),
                trace_id=str(owned.control_scope.trace_id),
                error_type=type(exc).__name__,
            )
            return None
        async with owner_transaction(
            self._factory, owned.control_scope, identity, owned.execution.task_id
        ) as (session, row):
            now = await db_now(session)
            require_owner_lease(row, owned.owner_lease(), now)
            fresh, hold = await billing_request(session, row, owned)
            if observation is None:
                return None
            observation = BillingObservation.model_validate_json(observation.model_dump_json())
            require_observation(fresh, observation)
            await self._resolver.validate_before_commit(session, fresh, observation, now)
            return await record_bill(session, row, hold, fresh, observation, now)

    async def _request(
        self, owned: OwnerBillingLease, identity: VerifiedIdentity
    ) -> BillingLookupRequest:
        async with owner_transaction(
            self._factory, owned.control_scope, identity, owned.execution.task_id
        ) as (session, row):
            require_owner_lease(row, owned.owner_lease(), await db_now(session))
            request, _ = await billing_request(session, row, owned)
            return request

    async def renew(
        self, owned: OwnerBillingLease, identity: VerifiedIdentity, *, ttl_seconds: int = 60
    ) -> OwnerBillingLease:
        async with owner_transaction(
            self._factory, owned.control_scope, identity, owned.execution.task_id
        ) as (session, row):
            now = await db_now(session)
            require_owner_lease(row, owned.owner_lease(), now)
            await billing_request(session, row, owned)
            row.lease_until = max(row.lease_until or now, now + _ttl(ttl_seconds))
            await session.flush()
            return OwnerBillingLease.model_validate(owned.model_dump() | {"execution": _lease(row)})

    async def release(
        self, owned: OwnerBillingLease, identity: VerifiedIdentity
    ) -> ExecutionSnapshot:
        async with owner_transaction(
            self._factory, owned.control_scope, identity, owned.execution.task_id
        ) as (session, row):
            require_owner_lease(row, owned.owner_lease(), await db_now(session))
            await billing_request(session, row, owned)
            row.fence += 1
            row.worker_id = row.lease_until = row.lease_mode = row.lease_principal_id = None
            await session.flush()
            return snapshot(row)
