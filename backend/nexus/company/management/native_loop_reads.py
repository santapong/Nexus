"""Current signed-owner native occurrence inspection under the company mutex; no effects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.event_models import BrainEvent
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_models import ManagementWorkAcceptance
from nexus.company.management.acceptance_persistence import acceptance_record
from nexus.company.management.cancellation_support import cancellation_for_work
from nexus.company.management.control_models import ManagementControlEvent
from nexus.company.management.native_loop_actions import require_loop_action
from nexus.company.management.native_loop_contracts import NativeOperatingRegistration
from nexus.company.management.native_profile_contracts import NativeReportOperatingProfile
from nexus.company.management.native_profile_lookup import load_profile, report_record
from nexus.company.management.report_input_contracts import native_author
from nexus.company.management.scheduling_contracts import EventWake
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.effect_support import effect_record, require_receipt_binding
from nexus.execution.management_checks import current_accepted_work
from nexus.execution.native_report_services import NativeReportServices
from nexus.execution.runtime_contracts import EffectRecord, ExecutionSnapshot
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import db_now, snapshot
from nexus.harness.journal_contracts import ActionRecord
from nexus.harness.journal_models import CostHold, JournalAction
from nexus.harness.journal_submission import pending_action_record


@dataclass(frozen=True)
class LoopWork:
    """Immutable read projection, with no ORM objects or reusable authority."""

    execution: ExecutionSnapshot
    action: ActionRecord | None
    effect: EffectRecord | None
    dispatch: bool
    billing_unknown: bool


@dataclass(frozen=True)
class LoopSnapshot:
    observed_at: datetime
    profile: NativeReportOperatingProfile | None
    author: LoopWork
    verifier: LoopWork
    stopped: str | None
    acceptance: WorkAcceptance | None
    historical: WorkAcceptance | None


async def _work(
    session: AsyncSession,
    registration: NativeOperatingRegistration,
    work: ExecutionWork,
    phase: Literal["author", "verifier"],
    native: NativeReportServices,
) -> LoopWork:
    action_id = registration.action_id("author" if phase == "author" else "verifier")
    action = await session.get(JournalAction, action_id)
    issued = await session.get(EffectIntent, (work.company_id, action_id))
    dispatch = await session.get(SegmentDispatch, (work.company_id, action_id))
    hold = await session.get(CostHold, action_id)
    record = pending_action_record(action) if action else None
    effect = effect_record(issued) if issued else None
    if record is not None:
        rule = native.publisher.rules.get(
            "company.report.write.v1" if phase == "author" else "company.report.check.v1"
        )
        if rule is None:
            raise ManagementDeniedError("Native loop tool rule is unavailable")
        require_loop_action(registration, work, phase, record, rule)
    if issued is not None:
        if record is None or (issued.task_id, issued.run_id, issued.proposal_hash) != (
            work.task_id,
            work.run_id,
            record.proposal_hash,
        ):
            raise ManagementDeniedError("Registered loop issued result differs from exact action")
        if effect is not None and effect.receipt is not None:
            require_receipt_binding(issued, effect.receipt)
    return LoopWork(
        snapshot(work),
        record,
        effect,
        dispatch is not None,
        bool(issued and hold and hold.state == "unknown"),
    )


async def _event(
    session: AsyncSession, registration: NativeOperatingRegistration, wake: EventWake | None
) -> None:
    if wake is not None:
        model = BrainEvent if wake.stream == "brain" else ManagementControlEvent
        if await session.get(model, (registration.company_id, wake.event_id)) is None:
            raise ManagementDeniedError("Native loop event is unavailable")


async def inspect_loop(
    factory: async_sessionmaker[AsyncSession],
    registration: NativeOperatingRegistration,
    native: NativeReportServices,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    event: EventWake | None,
) -> LoopSnapshot:
    """Actual owner audit/current proof reads share CompanyControl; nothing is registered here."""
    # Atomic read snapshot: exact owner/native records, stopped history, current
    # acceptance and the final database clock must agree under one company mutex.
    async with management_owner_transaction(factory, scope, identity, allow_paused=True) as (
        session,
        control,
        _,
    ):
        if scope.company_id != registration.company_id:
            raise ManagementDeniedError("Native loop company differs from trusted registration")
        await _event(session, registration, event)
        saved = await report_record(
            session, registration.company_id, registration.profile.report_id
        )
        rows = []
        for binding in (saved.selection.author, saved.selection.verifier):
            row = await session.get(ExecutionWork, (scope.company_id, binding.task_id))
            if row is None or native_author(row)[0] != binding:
                raise ManagementDeniedError("Native loop exact work registration is unavailable")
            rows.append(row)
        author, verifier = rows
        stopped = "company_paused" if control.paused else None
        for row in rows:
            if await cancellation_for_work(
                session, row.company_id, row.task_id, trace_id=row.trace_id, run_id=row.run_id
            ):
                stopped = "work_cancelled"
        profile = None
        try:
            profile, _ = await load_profile(
                session,
                control,
                scope,
                registration.profile,
                require_due=False,
                now=await db_now(session),
            )
        except ValueError:
            stopped = stopped or "profile_not_current"
        history_row = await session.scalar(
            select(ManagementWorkAcceptance)
            .where(
                ManagementWorkAcceptance.company_id == scope.company_id,
                ManagementWorkAcceptance.action_id == registration.action_id("author"),
            )
            .limit(1)
        )
        history = acceptance_record(history_row) if history_row else None
        author_view = await _work(session, registration, author, "author", native)
        verifier_view = await _work(session, registration, verifier, "verifier", native)
        observed = await db_now(session)
        accepted = await current_accepted_work(
            session, control, author, author, identity, native.artifacts, native.publisher.freshness
        )
        if accepted is not None and accepted.target.action_id != registration.action_id("author"):
            accepted = None
        return LoopSnapshot(
            observed,
            profile,
            author_view,
            verifier_view,
            stopped,
            accepted,
            history,
        )
