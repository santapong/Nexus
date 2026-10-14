"""Bounded native selected work/receipt/leaf-charge reads under the company mutex."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.directory_models import RegisteredWork
from nexus.company.directory_store import _lineage_active
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.cancellation_support import cancellation_for_work
from nexus.company.management.eligibility_rules import AcceptedWork
from nexus.company.management.operating_report_billing import charge_rows, latest_receipt
from nexus.company.management.operating_report_contracts import ReportData, ReportSelection
from nexus.company.management.operating_report_history import work_history
from nexus.company.management.operating_report_invoices import billing_proofs
from nexus.company.management.operating_report_resources import (
    report_resources,
    selection_resources,
)
from nexus.company.management.plan_models import ManagementOwnerDecision
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.report_inputs import native_author
from nexus.company.management.report_rules import WorkLineage, WorkReportFacts
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.journal_models import CompanyControl


async def capture_data(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    selection: ReportSelection,
    catalog: PlanAdmissionCatalog,
    artifacts: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
) -> ReportData:
    ids = tuple(row.task_id for row in selection.work)
    states, references = await selected_states(
        session, control, scope, identity, selection, artifacts, freshness
    )
    charges, missing = await charge_rows(session, scope, ids)
    source_ids = await selection_resources(session, scope, selection, catalog)
    resources, generations, current_heads = await report_resources(
        session,
        scope,
        source_ids,
        tuple({row.artifact_revision_id: row for row in references}.values()),
    )
    decisions = tuple(
        (
            await session.scalars(
                select(ManagementOwnerDecision.decision_id)
                .where(
                    ManagementOwnerDecision.company_id == scope.company_id,
                    ManagementOwnerDecision.plan_revision_id == selection.plan.plan_revision_id,
                )
                .order_by(ManagementOwnerDecision.recorded_at, ManagementOwnerDecision.decision_id)
            )
        ).all()
    )
    lineage = await lineage_rows(session, scope, selection)
    return ReportData(
        company_id=scope.company_id,
        lineage=lineage,
        work=tuple(states),
        charges=charges,
        missing_charge_ids=missing,
        owner_decision_ids=decisions,
        required_resource_ids=resources,
        resource_generations=generations,
        source_heads=current_heads,
    )


async def selected_states(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    selection: ReportSelection,
    artifacts: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
) -> tuple[list[WorkReportFacts], list[ArtifactRevisionRef]]:
    states: list[WorkReportFacts] = []
    references: list[ArtifactRevisionRef] = []
    for binding in selection.work:
        row = await session.get(ExecutionWork, (scope.company_id, binding.task_id))
        registered = await session.get(RegisteredWork, (scope.company_id, binding.task_id))
        require_acceptance(row is not None and registered is not None)
        assert row is not None and registered is not None
        require_acceptance(native_author(row)[0] == binding)
        reader = (
            await session.get(ExecutionWork, (scope.company_id, scope.task_id))
            if scope.task_id
            else row
        )
        require_acceptance(reader is not None)
        assert reader is not None
        acceptance, proofs = await work_history(
            session, control, reader, row, identity, artifacts, freshness
        )
        references.extend(proofs)
        references.extend(await billing_proofs(session, row))
        state = await work_state(session, row, registered, acceptance, references)
        states.append(state)
    return states, references


async def work_state(
    session: AsyncSession,
    row: ExecutionWork,
    registered: RegisteredWork,
    acceptance: AcceptedWork,
    references: list[ArtifactRevisionRef],
) -> WorkReportFacts:
    latest = await latest_receipt(session, row, references)
    cancellation = await cancellation_for_work(
        session, row.company_id, row.task_id, trace_id=row.trace_id, run_id=row.run_id
    )
    blockers = tuple(
        value
        for value, applies in (
            ("inactive_work", not await _lineage_active(session, registered)),
            ("outcome_unknown", row.state == "outcome_unknown"),
            ("blocked_work", row.state == "blocked"),
            ("owner_cancelled", cancellation is not None),
        )
        if applies
    )
    return WorkReportFacts.model_validate(
        {
            "company_id": row.company_id,
            "work": native_author(row)[0],
            "execution_state": row.state,
            "registered_active": await _lineage_active(session, registered),
            "cancelled": cancellation is not None,
            "acceptance": acceptance,
            "receipt": latest,
            "verification_candidate": None,
            "blockers": blockers,
        }
    )


async def lineage_rows(
    session: AsyncSession, scope: BrainReadScope, selection: ReportSelection
) -> tuple[WorkLineage, ...]:
    keys = {row.task_id for row in selection.work}
    if not keys:
        row = await session.get(ExecutionWork, (scope.company_id, selection.author.task_id))
        registered = await session.get(RegisteredWork, (scope.company_id, selection.author.task_id))
        require_acceptance(row is not None and registered is not None)
        assert registered is not None
        keys.add(registered.root_task_id)
    result: dict[UUID, WorkLineage] = {}
    while keys:
        key = keys.pop()
        row = await session.get(ExecutionWork, (scope.company_id, key))
        registered = await session.get(RegisteredWork, (scope.company_id, key))
        require_acceptance(row is not None and registered is not None and len(result) < 101)
        assert row is not None and registered is not None
        result[key] = WorkLineage(
            company_id=scope.company_id,
            work=native_author(row)[0],
            parent_task_id=registered.parent_task_id,
            root_task_id=registered.root_task_id,
        )
        if registered.parent_task_id is not None and registered.parent_task_id not in result:
            keys.add(registered.parent_task_id)
    return tuple(result[key] for key in sorted(result))
