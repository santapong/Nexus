"""Native owner work observations sanitize issued facts and independent acceptance history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.directory_models import RegisteredWork
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_models import (
    ManagementAcceptanceInvalidation,
    ManagementWorkAcceptance,
)
from nexus.company.management.acceptance_persistence import acceptance_record
from nexus.company.management.cancellation_support import cancellation_for_work
from nexus.company.management.control_support import db_clock
from nexus.company.management.owner_view_budget import lifetime_budget
from nexus.company.management.owner_view_contracts import AcceptanceAudit, ReceiptAudit, WorkView
from nexus.company.management.owner_view_sources import (
    OwnerViewSources,
    SourceDisclosure,
    source_disclosure,
)
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import RunBinding
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.effect_support import require_receipt_binding
from nexus.execution.management_checks import current_accepted_work
from nexus.execution.runtime_contracts import EffectState
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import snapshot
from nexus.harness.journal_models import CompanyControl, CostHold

EMPTY_ACCEPTANCE = AcceptanceAudit(
    acceptance_id=None,
    historical_verdict=None,
    recorded_at=None,
    invalidated=False,
    current_confirmed=False,
)


@dataclass(frozen=True)
class WorkObservation:
    value: WorkView
    disclosure: SourceDisclosure | None

    def render(self, now: datetime) -> WorkView:
        if self.disclosure is not None and self.disclosure.permits(now):
            return self.value
        audit = self.value.independent_acceptance.model_copy(
            update={
                "current_confirmed": False,
                "authorized_proofs": None,
            }
        )
        return WorkView.model_validate_json(
            self.value.model_copy(update={"independent_acceptance": audit}).model_dump_json()
        )


def work_binding(work: ExecutionWork) -> RunBinding:
    registered = snapshot(work).registration
    return RunBinding(
        company_id=work.company_id,
        workspace_id=work.workspace_id,
        actor_id=work.actor_id,
        task_id=work.task_id,
        trace_id=work.trace_id,
        run_id=work.run_id,
        workflow_name=registered.workflow_name,
        workflow_version=registered.workflow_version,
        model_profile=registered.model_profile,
        model_registry_version=registered.model_registry_version,
    )


async def lineage_active(session: AsyncSession, work: ExecutionWork) -> bool:
    visited: set[UUID] = set()
    task: UUID | None = work.task_id
    while task is not None and len(visited) < 16:
        if task in visited:
            return False
        visited.add(task)
        row = await session.get(RegisteredWork, (work.company_id, task))
        if row is None or not row.active:
            return False
        task = row.parent_task_id
    return task is None


async def acceptance_audit(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    work: ExecutionWork,
    sources: OwnerViewSources | None,
) -> tuple[AcceptanceAudit, SourceDisclosure | None]:
    historical, invalidated = await _acceptance_history(session, control, work)
    if historical is None:
        return EMPTY_ACCEPTANCE, None
    current = (
        await current_accepted_work(
            session, control, work, work, identity, sources.artifacts, sources.freshness
        )
        if sources is not None
        else None
    )
    refs = (
        tuple(
            {
                ref.artifact_revision_id: ref
                for ref in (
                    *current.target.artifacts,
                    *(proof.result_artifact for proof in current.proofs),
                )
            }.values()
        )
        if current is not None
        else ()
    )
    disclosure = (
        await source_disclosure(session, control, scope, identity, sources, refs)
        if current is not None
        else None
    )
    confirmed = current is not None and disclosure is not None
    return AcceptanceAudit(
        acceptance_id=historical.acceptance_id,
        historical_verdict=historical.verdict,
        recorded_at=historical.recorded_at,
        invalidated=invalidated,
        current_confirmed=confirmed,
        authorized_proofs=current.proofs if confirmed and current is not None else None,
    ), disclosure


async def _acceptance_history(
    session: AsyncSession,
    control: CompanyControl,
    work: ExecutionWork,
) -> tuple[WorkAcceptance | None, bool]:
    native = await session.scalar(
        select(ManagementWorkAcceptance)
        .where(
            ManagementWorkAcceptance.company_id == control.company_id,
            ManagementWorkAcceptance.author_task_id == work.task_id,
            ManagementWorkAcceptance.author_run_id == work.run_id,
        )
        .order_by(
            ManagementWorkAcceptance.recorded_at.desc(),
            ManagementWorkAcceptance.acceptance_id.desc(),
        )
        .limit(1)
    )
    if native is None:
        return None, False
    historical = acceptance_record(native)
    invalidated = (
        await session.scalar(
            select(ManagementAcceptanceInvalidation.invalidation_id)
            .where(
                ManagementAcceptanceInvalidation.company_id == control.company_id,
                ManagementAcceptanceInvalidation.acceptance_id == historical.acceptance_id,
            )
            .limit(1)
        )
        is not None
    )
    return historical, invalidated


async def receipt_audit(
    session: AsyncSession,
    work: ExecutionWork,
) -> tuple[tuple[ReceiptAudit, ...], UUID | None]:
    rows = tuple(
        (
            await session.scalars(
                select(EffectIntent)
                .where(
                    EffectIntent.company_id == work.company_id,
                    EffectIntent.task_id == work.task_id,
                    EffectIntent.run_id == work.run_id,
                )
                .order_by(EffectIntent.action_id)
                .limit(101)
            )
        ).all()
    )
    result = []
    for row in rows[:100]:
        from nexus.company.contracts.results import ActionReceipt

        actual = ActionReceipt.model_validate_json(row.receipt_json) if row.receipt_json else None
        if actual is not None:
            require_receipt_binding(row, actual)
        hold = await session.get(CostHold, row.action_id)
        result.append(
            ReceiptAudit(
                action_id=row.action_id,
                state=cast(EffectState, row.state),
                receipt_id=actual.receipt_id if actual else None,
                known_cost_usd=hold.actual_usd if hold else None,
                billing="known"
                if hold is not None and hold.actual_usd is not None
                else "unconfirmed",
            )
        )
    return tuple(result), rows[99].action_id if len(rows) > 100 else None


async def observe_work(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    work: ExecutionWork,
    sources: OwnerViewSources | None,
) -> WorkObservation:
    native = await session.get(RegisteredWork, (control.company_id, work.task_id))
    if native is None or work.company_id != scope.company_id:
        raise ManagementDeniedError("Owner work view is unavailable")
    actual = snapshot(work)
    binding = await ManagementPlanStore.current_binding(session, control.company_id, work.task_id)
    acceptance, disclosure = await acceptance_audit(
        session, control, scope, identity, work, sources
    )
    receipts, next_id = await receipt_audit(session, work)
    now = await db_clock(session)
    return WorkObservation(
        WorkView(
            company_id=scope.company_id,
            work=work_binding(work),
            title=actual.registration.work.title,
            execution_state=actual.state,
            registered_active=native.active,
            lineage_active=await lineage_active(session, work),
            cancellation=await cancellation_for_work(
                session, work.company_id, work.task_id, trace_id=work.trace_id, run_id=work.run_id
            ),
            current_plan=binding.plan if binding else None,
            independent_acceptance=acceptance,
            lifetime=await lifetime_budget(session, control, work),
            live_lease_until=work.lease_until
            if work.lease_until and work.lease_until > now
            else None,
            receipts=receipts,
            receipts_next_after_id=next_id,
        ),
        disclosure,
    )
