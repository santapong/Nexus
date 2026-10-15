"""Fenced committed effect intent and receipts; actual invocation belongs to a trusted adapter."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import StrictBool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.contracts.results import ActionReceipt, VerificationResult
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.execution.effect_support import (
    effect_record,
    effect_row,
    require_effect_authority,
    require_receipt_binding,
)
from nexus.execution.intent_checks import BeforeIntentCheck, FinalIntentTimeCheck
from nexus.execution.management_checks import (
    ManagementArtifactFreshness,
    require_management_execution,
)
from nexus.execution.receipt_events import ReceiptEventPublisher
from nexus.execution.runtime_contracts import (
    AttemptKind,
    EffectRecord,
    EffectStart,
    ExecutionDeniedError,
    ExecutionLease,
)
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    require_lease,
    reserve_locked_attempt,
    runtime_transaction,
    snapshot,
)
from nexus.harness.journal_budget import reconcile_cost
from nexus.harness.journal_models import CompanyControl
from nexus.harness.journal_reservations import hold_to_effect_day


class EffectStore:
    """No HTTP/provider execution, no receiver fencing and no exactly-once effect promise."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        *,
        management_catalog: PlanAdmissionCatalog | None = None,
        management_artifacts: BoundedArtifactReader | None = None,
        management_freshness: ManagementArtifactFreshness | None = None,
        receipt_events: ReceiptEventPublisher | None = None,
    ) -> None:
        self._factory = factory
        self._management_catalog = management_catalog
        self._management_artifacts = management_artifacts
        self._management_freshness = management_freshness
        self._receipt_events = receipt_events

    # Keep this >50-line transaction boundary together: current authority, held
    # cost, lifetime attempt and committed intent must share the company lock.
    async def begin(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        action_id: UUID,
        *,
        resources: tuple[ResourceRevision, ...] = (),
        kind: AttemptKind = "tool_attempts",
        before_intent: BeforeIntentCheck | None = None,
    ) -> EffectStart:
        """Return one permit only after exact authority, quota and intent have committed."""
        if kind not in {"model_requests", "tool_attempts"} or lease.mode != "execute":
            raise ExecutionDeniedError("Only an execute lease can start model/tool effects")
        async with runtime_transaction(self._factory, lease_scope(lease), identity) as (
            session,
            control,
            _,
        ):
            work = await execution_row(session, lease_scope(lease))
            now = await db_now(session)
            require_lease(work, lease, now)
            previous = await session.get(EffectIntent, (work.company_id, action_id))
            if previous is not None:
                if (previous.task_id, previous.run_id, previous.attempt_kind) != (
                    work.task_id,
                    work.run_id,
                    kind,
                ):
                    raise ExecutionDeniedError("Effect identity already binds another run/kind")
                return EffectStart(record=effect_record(previous), permit_external_call=False)
            require_lease(work, lease, now, execute=True)
            action = await require_effect_authority(
                session, control, work, action_id, now, resources, lease_scope(lease), identity
            )
            from nexus.execution.selected_intent_gate import require_selected_intent_check

            require_selected_intent_check(
                self._management_catalog, work, lease, identity, action, before_intent
            )
            from nexus.company.notifications.mixed_worker_intent import (
                require_mixed_notification_intent_check,
            )

            require_mixed_notification_intent_check(
                self._management_catalog, work, lease, identity, action, before_intent
            )
            if before_intent is not None:
                await before_intent.validate(session, control, work, action, now)
            active = await session.scalar(
                select(EffectIntent.action_id).where(
                    EffectIntent.company_id == work.company_id,
                    EffectIntent.task_id == work.task_id,
                    EffectIntent.state.in_(("intent", "outcome_unknown")),
                )
            )
            if active is not None:
                raise ExecutionDeniedError(
                    "Another unresolved intent requires reconciliation first"
                )
            # The company lock serializes writes, but wall-clock authority/lease
            # expiry can cross a bounded estimator or provenance check.
            await self.revalidate_execution_locked(
                session,
                control,
                work,
                identity,
                ActionProposal.model_validate_json(action.proposal_json),
                kind,
            )
            now = await db_now(session)
            require_lease(work, lease, now, execute=True)
            action = await require_effect_authority(
                session, control, work, action_id, now, resources, lease_scope(lease), identity
            )
            try:
                await hold_to_effect_day(session, control, lease_scope(lease), action_id, now)
            except ValueError as exc:
                raise ExecutionDeniedError("Current effect-day reservation is unavailable") from exc
            await reserve_locked_attempt(session, work, kind, action_id, now)
            row = EffectIntent(
                company_id=work.company_id,
                action_id=action_id,
                task_id=work.task_id,
                trace_id=work.trace_id,
                run_id=work.run_id,
                proposal_hash=action.proposal_hash,
                intent_fence=work.fence,
                attempt_kind=kind,
                state="intent",
                created_at=now,
                receipt_json=None,
                verification_json=None,
            )
            session.add(row)
            await session.flush()
            if isinstance(before_intent, FinalIntentTimeCheck):
                final = await db_now(session)
                require_lease(work, lease, final, execute=True)
                before_intent.validate_time(final)
            return EffectStart(record=effect_record(row), permit_external_call=True)

    async def revalidate_execution_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        identity: VerifiedIdentity,
        proposal: ActionProposal,
        kind: AttemptKind,
    ) -> None:
        """Recheck actual configured managed admission under the caller's company lock.

        This provides no lease, approval or permit. Callers retain those independent
        checks. It may deny post-intent execution when current governance changed;
        already-issued terminal receipt/reconciliation does not call this gate.
        """
        await require_management_execution(
            session,
            control,
            work,
            identity,
            self._management_catalog,
            self._management_artifacts,
            self._management_freshness,
            proposal,
            kind,
        )

    async def get(
        self, lease: ExecutionLease, identity: VerifiedIdentity, action_id: UUID
    ) -> EffectRecord:
        """Read a known receipt/intent through the currently fenced trusted worker."""
        async with runtime_transaction(
            self._factory, lease_scope(lease), identity, allow_paused=True, allow_inactive=True
        ) as (session, _, _):
            work = await execution_row(session, lease_scope(lease))
            require_lease(work, lease, await db_now(session))
            return effect_record(await effect_row(session, work, action_id))

    async def record_receipt(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        receipt: ActionReceipt,
        *,
        actual_usd: Decimal | None = None,
        blocked: StrictBool = False,
    ) -> EffectRecord:
        """Record an already-issued outcome; no stale worker or conflicting receipt may win."""
        return await self._record(
            lease, identity, receipt, actual_usd, reconcile=False, blocked=blocked
        )

    async def reconcile(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        receipt: ActionReceipt,
        *,
        actual_usd: Decimal | None = None,
    ) -> EffectRecord:
        """Resolve an issued unknown effect under the new fence, including while paused."""
        return await self._record(lease, identity, receipt, actual_usd, reconcile=True)

    # Keep this >50-line atomic receipt/cost/event boundary together: every write
    # and the final hook lease clock must commit under the same company mutex.
    async def _record(
        self,
        lease: ExecutionLease,
        identity: VerifiedIdentity,
        receipt: ActionReceipt,
        actual_usd: Decimal | None,
        *,
        reconcile: bool,
        blocked: StrictBool = False,
    ) -> EffectRecord:
        receipt = ActionReceipt.model_validate_json(receipt.model_dump_json())
        if type(blocked) is not bool or (blocked and receipt.outcome != "failed"):
            raise ExecutionDeniedError("Only a failed receipt may request a literal terminal block")
        async with runtime_transaction(
            self._factory, lease_scope(lease), identity, allow_paused=True, allow_inactive=True
        ) as (session, control, _):
            work = await execution_row(session, lease_scope(lease))
            require_lease(work, lease, await db_now(session))
            row = await effect_row(session, work, receipt.action_id)
            require_receipt_binding(row, receipt)
            if row.state in {"succeeded", "failed"}:
                if row.receipt_json != receipt.model_dump_json():
                    raise ExecutionDeniedError(
                        "Known receipt is immutable; conflicting outcome denied"
                    )
            else:
                if reconcile and row.state != "outcome_unknown":
                    raise ExecutionDeniedError(
                        "Reconciliation needs a previously unknown issued effect"
                    )
                if not reconcile and (row.state != "intent" or row.intent_fence != lease.fence):
                    raise ExecutionDeniedError(
                        "Receipt requires its current original effect intent"
                    )
                row.receipt_json, row.state = receipt.model_dump_json(), receipt.outcome
                work.state = (
                    "verifying"
                    if receipt.outcome == "succeeded"
                    else ("outcome_unknown" if receipt.outcome == "outcome_unknown" else "running")
                )
            if blocked:
                work.state = "blocked"
            await reconcile_cost(session, lease_scope(lease), receipt.action_id, actual_usd)
            await session.flush()
            if self._receipt_events is not None:
                await self._receipt_events.publish(
                    session, control, work, row, receipt, identity, await db_now(session)
                )
                await session.flush()
                require_lease(work, lease, await db_now(session))
            return effect_record(row)

    async def record_verification_candidate(
        self, lease: ExecutionLease, identity: VerifiedIdentity, result: VerificationResult
    ) -> EffectRecord:
        """Store a format-bound candidate, never publish or complete work from a raw verdict.

        Company acceptance needs independent evidence lookup in the later verifier.
        This record preserves a candidate; state remains verifying even on `pass`.
        """
        async with runtime_transaction(
            self._factory, lease_scope(lease), identity, allow_paused=True, allow_inactive=True
        ) as (session, _, _):
            work = await execution_row(session, lease_scope(lease))
            require_lease(work, lease, await db_now(session))
            row = await effect_row(session, work, result.action_id)
            return await _verification(session, work, row, result)


async def _verification(
    session: AsyncSession, work: ExecutionWork, row: EffectIntent, result: VerificationResult
) -> EffectRecord:
    result = VerificationResult.model_validate_json(result.model_dump_json())
    if (
        row.state != "succeeded"
        or result.company_id != row.company_id
        or (
            result.verifier_id == work.actor_id
            or set(result.criterion_ids) != set(snapshot(work).registration.work.acceptance)
        )
    ):
        raise ExecutionDeniedError(
            "Candidate requires a successful receipt and distinct bound verifier/criteria"
        )
    payload = result.model_dump_json()
    if row.verification_json is not None and row.verification_json != payload:
        raise ExecutionDeniedError("Recorded verification candidate is immutable")
    row.verification_json = payload
    await session.flush()
    return effect_record(row)
