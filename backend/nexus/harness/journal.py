"""Standalone PostgreSQL approval/cost journal; no legacy API/runtime activation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal, ApprovalDecision, ResourceRevision
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dbos_queue import enqueue_authorized_segment
from nexus.harness.journal_authorization import authorize_locked as _authorize_locked
from nexus.harness.journal_budget import (
    budget_snapshot,
    reconcile_cost,
    require_registered_access,
)
from nexus.harness.journal_contracts import ActionRecord, BudgetSnapshot, CompanyPolicy, LedgerScope
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.journal_submission import submit_pending_locked
from nexus.harness.lifecycle import ActionState, require_transition

logger = structlog.get_logger()


def _record(row: JournalAction) -> ActionRecord:
    return ActionRecord(
        company_id=row.company_id,
        proposal=ActionProposal.model_validate_json(row.proposal_json),
        proposal_hash=row.proposal_hash,
        state=ActionState(row.state),
        consumed_at=row.consumed_at,
        approval=ApprovalDecision.model_validate_json(row.approval_json)
        if row.approval_json
        else None,
    )


async def _control(session: AsyncSession, scope: LedgerScope) -> CompanyControl:
    control = await session.scalar(
        select(CompanyControl)
        .where(
            CompanyControl.company_id == scope.company_id,
        )
        .with_for_update()
    )
    if control is None:
        raise ValueError("Company is unavailable in this scope")
    return control


async def _action(session: AsyncSession, scope: LedgerScope, action_id: UUID) -> JournalAction:
    row = await session.scalar(
        select(JournalAction).where(
            JournalAction.company_id == scope.company_id,
            JournalAction.id == action_id,
            JournalAction.task_id == scope.task_id,
        )
    )
    if row is None:
        raise ValueError("Action is unavailable in this scope")
    return row


def _approve_locked(
    row: JournalAction,
    control: CompanyControl,
    scope: LedgerScope,
    expected_hash: str,
    now: datetime,
    approved: bool,
) -> ActionRecord:
    if scope.principal_id != control.owner_id or row.proposal_hash != expected_hash:
        raise ValueError("Owner or expected proposal hash does not match")
    requested: Literal["approved", "rejected"] = "approved" if approved else "rejected"
    if row.approval_json:
        previous = _record(row).approval
        if previous is None or previous.decision != requested:
            raise ValueError("Decision is immutable")
        return _record(row)
    if row.state != ActionState.AWAITING_APPROVAL:
        raise ValueError("Action is not awaiting an owner decision")
    proposal = ActionProposal.model_validate_json(row.proposal_json)
    decision = ApprovalDecision(
        company_id=scope.company_id,
        decision_id=uuid4(),
        action_id=row.id,
        action_revision=proposal.revision,
        action_hash=expected_hash,
        approver_id=scope.principal_id,
        decision=requested,
        issued_at=now,
        expires_at=now + timedelta(hours=24),
    )
    row.approval_json = decision.model_dump_json()
    if not approved:
        require_transition(ActionState(row.state), ActionState.REJECTED)
        row.state = ActionState.REJECTED.value
    return _record(row)


class CompanyJournal:
    """Commit exact approvals and cost holds through trusted server-derived scope.

    Registered methods recheck current directory authority and lifetime work
    allocations. Standalone methods preserve the original isolated test path.
    Tool policy, provider conformance and external effects remain separate gates.
    """

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    @asynccontextmanager
    async def _session(self, scope: LedgerScope) -> AsyncIterator[AsyncSession]:
        async with self._factory() as session, session.begin():
            await session.execute(
                select(func.set_config("nexus.company_id", str(scope.company_id), True))
            )
            try:
                yield session
            except Exception as exc:
                logger.warning(
                    "company_journal_rejected",
                    company_id=str(scope.company_id),
                    task_id=str(scope.task_id),
                    trace_id=str(scope.trace_id),
                    error_type=type(exc).__name__,
                )
                raise

    async def create_company(self, policy: CompanyPolicy, scope: LedgerScope) -> None:
        """Register initial policy idempotently; caller must be its trusted owner."""
        if policy.company_id != scope.company_id or policy.owner_id != scope.principal_id:
            raise ValueError("Initial company registration requires its owner scope")
        async with self._session(scope) as session:
            existing = await session.get(CompanyControl, scope.company_id)
            if existing is not None:
                if (
                    existing.owner_id,
                    existing.policy_version,
                    existing.price_version,
                    existing.daily_cap_usd,
                    existing.work_cap_usd,
                ) != (
                    policy.owner_id,
                    policy.policy_version,
                    policy.price_version,
                    policy.daily_cap_usd,
                    policy.work_cap_usd,
                ):
                    raise ValueError("Company already has a different registered policy")
                return
            session.add(
                CompanyControl(
                    company_id=policy.company_id,
                    owner_id=policy.owner_id,
                    policy_version=policy.policy_version,
                    price_version=policy.price_version,
                    paused=False,
                    daily_cap_usd=policy.daily_cap_usd,
                    work_cap_usd=policy.work_cap_usd,
                )
            )

    async def submit(self, action: ActionProposal, scope: LedgerScope) -> ActionRecord:
        """Commit the exact pending proposal before any decision polling can occur."""
        async with self._session(scope) as session:
            control = await _control(session, scope)
            return await submit_pending_locked(session, control, action, scope)

    async def get_action(self, scope: LedgerScope, action_id: UUID) -> ActionRecord:
        """Read a committed record only for its actor or the company's owner."""
        async with self._session(scope) as session:
            control = await _control(session, scope)
            record = _record(await _action(session, scope, action_id))
            if scope.principal_id not in {control.owner_id, record.proposal.actor_id}:
                raise ValueError("Principal cannot read this action")
            return record

    async def approve(
        self,
        scope: LedgerScope,
        action_id: UUID,
        expected_hash: str,
        now: datetime,
        *,
        approved: bool = True,
    ) -> ActionRecord:
        """Commit an exact owner decision once; repeated decisions cannot renew expiry."""
        async with self._session(scope) as session:
            control = await _control(session, scope)
            row = await _action(session, scope, action_id)
            return _approve_locked(row, control, scope, expected_hash, now, approved)

    async def authorize(
        self,
        scope: LedgerScope,
        action_id: UUID,
        now: datetime,
        resources: tuple[ResourceRevision, ...],
    ) -> ActionRecord:
        """Atomically consume approval and reserve cost; this executes no effect."""
        async with self._session(scope) as session:
            control = await _control(session, scope)
            row = await _action(session, scope, action_id)
            return await _authorize_locked(
                session, row, control, scope, now, resources, registered=False
            )

    async def approve_registered(
        self,
        scope: LedgerScope,
        action_id: UUID,
        expected_hash: str,
        now: datetime,
        *,
        identity: VerifiedIdentity,
        approved: bool = True,
    ) -> ActionRecord:
        """Commit owner decision only after fresh same-transaction membership/work checks."""
        async with self._session(scope) as session:
            control = await _control(session, scope)
            row = await _action(session, scope, action_id)
            await require_registered_access(
                session, control, _record(row).proposal, scope, identity, owner=True
            )
            proposal = _record(row).proposal
            if (proposal.policy_version, proposal.price_version) != (
                control.policy_version,
                control.price_version,
            ):
                raise ValueError("Owner decision cannot approve stale policy or prices")
            return _approve_locked(row, control, scope, expected_hash, now, approved)

    async def authorize_registered(
        self,
        scope: LedgerScope,
        action_id: UUID,
        now: datetime,
        resources: tuple[ResourceRevision, ...],
        *,
        identity: VerifiedIdentity,
    ) -> ActionRecord:
        """Consume exact approval/current registered own allowance; execute no external effect."""
        async with self._session(scope) as session:
            control = await _control(session, scope)
            row = await _action(session, scope, action_id)
            await require_registered_access(
                session, control, _record(row).proposal, scope, identity, owner=False
            )
            return await _authorize_locked(
                session, row, control, scope, now, resources, registered=True
            )

    async def authorize_and_enqueue_registered(
        self,
        scope: LedgerScope,
        command: SegmentCommand,
        now: datetime,
        resources: tuple[ResourceRevision, ...],
        *,
        identity: VerifiedIdentity,
    ) -> str:
        """Commit current authorization, cost hold and trusted segment enqueue atomically.

        The caller supplies a server-authored command whose persistent runtime
        run/segment binding has already been validated; this is not HTTP intake.
        No provider/tool effect occurs. Enqueue failure rolls back all changes.
        """
        command = SegmentCommand.model_validate(command.model_dump())
        command.require_scope(scope)
        if command.workspace_id != identity.workspace_id:
            raise ValueError("Continuation and verified workspace disagree")
        async with self._session(scope) as session:
            control = await _control(session, scope)
            row = await _action(session, scope, command.action_id)
            await require_registered_access(
                session, control, _record(row).proposal, scope, identity, owner=False
            )
            await _authorize_locked(session, row, control, scope, now, resources, registered=True)
            await session.flush()
            return await enqueue_authorized_segment(session, command, scope)

    async def set_paused(self, scope: LedgerScope, paused: bool) -> None:
        """Persist owner pause so a new worker cannot authorize through restart."""
        async with self._session(scope) as session:
            control = await _control(session, scope)
            if scope.principal_id != control.owner_id:
                raise ValueError("Only the owner can change company pause")
            control.paused = paused

    async def reconcile(
        self,
        scope: LedgerScope,
        action_id: UUID,
        actual_usd: Decimal | None,
    ) -> None:
        """Resolve billing once; unknown billing retains its original reservation."""
        async with self._session(scope) as session:
            control = await _control(session, scope)
            row = await _action(session, scope, action_id)
            actor = _record(row).proposal.actor_id
            if scope.principal_id not in {control.owner_id, actor}:
                raise ValueError("Principal cannot reconcile this action")
            await reconcile_cost(session, scope, action_id, actual_usd)

    async def budget(self, scope: LedgerScope, now: datetime) -> BudgetSnapshot:
        """Read held and spent totals through the trusted internal company scope."""
        async with self._session(scope) as session:
            control = await _control(session, scope)
            return await budget_snapshot(session, control, scope, now)
