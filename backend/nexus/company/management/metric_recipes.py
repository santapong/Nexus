"""Native exact report count read recipe; a candidate or unavailable proof cannot count."""

from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance import WorkAcceptance
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.acceptance_models import ManagementWorkAcceptance
from nexus.company.management.acceptance_persistence import acceptance_record
from nexus.company.management.acceptance_support import actual_receipt
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.check_contracts import REPORT_CHECK_CRITERIA, REPORT_CHECK_RECIPE
from nexus.company.management.metric_contracts import MetricWorkFact
from nexus.company.management.metric_support import SelectedMetricWork
from nexus.execution.management_checks import current_accepted_work
from nexus.harness.journal_models import CompanyControl, JournalAction


async def report_fact(
    session: AsyncSession,
    control: CompanyControl,
    identity: VerifiedIdentity,
    selected: SelectedMetricWork,
    artifacts: BoundedArtifactReader,
    freshness: RegisteredSourceFreshness,
) -> MetricWorkFact:
    native = selected.native
    row = await latest_acceptance(session, selected)
    if row is None:
        return empty_fact(selected, "not_accepted")
    try:
        historic = acceptance_record(row)
        if historic.verdict != "pass":
            return empty_fact(selected, "not_accepted")
        current = await current_accepted_work(
            session,
            control,
            native,
            native,
            identity,
            artifacts,
            freshness,
        )
        if current is None:
            return empty_fact(selected, "unknown")
        action = await session.get(JournalAction, current.target.action_id)
        if action is None or action.company_id != native.company_id:
            return empty_fact(selected, "unknown")
        proposal = ActionProposal.model_validate_json(action.proposal_json)
        if proposal.tool != "company.report.write.v1" or (
            proposal.tool_version != "v1"
            or current.target.check_recipe != REPORT_CHECK_RECIPE
            or current.target.criterion_ids != REPORT_CHECK_CRITERIA
            or len(current.proofs) != 1
        ):
            return empty_fact(selected, "unknown")
        receipt = await actual_receipt(session, native, current.target.action_id)
        return accepted_fact(selected, current, receipt.recorded_at)
    except ValueError:
        return empty_fact(selected, "unknown")


async def latest_acceptance(
    session: AsyncSession,
    selected: SelectedMetricWork,
) -> ManagementWorkAcceptance | None:
    native = selected.native
    row: ManagementWorkAcceptance | None = await session.scalar(
        select(ManagementWorkAcceptance)
        .where(
            ManagementWorkAcceptance.company_id == native.company_id,
            ManagementWorkAcceptance.author_task_id == native.task_id,
            ManagementWorkAcceptance.author_run_id == native.run_id,
        )
        .order_by(
            ManagementWorkAcceptance.recorded_at.desc(),
            ManagementWorkAcceptance.acceptance_id.desc(),
        )
        .limit(1)
    )
    return row


def empty_fact(
    selected: SelectedMetricWork,
    status: Literal["not_accepted", "unknown"],
) -> MetricWorkFact:
    return MetricWorkFact(
        company_id=selected.native.company_id,
        work=selected.binding.child.binding,
        registration_sha256=selected.native.registration_hash,
        acceptance_id=None,
        acceptance_sha256=None,
        receipt_id=None,
        status=status,
    )


def accepted_fact(
    selected: SelectedMetricWork,
    record: WorkAcceptance,
    receipt_recorded_at: datetime,
) -> MetricWorkFact:
    return MetricWorkFact(
        company_id=selected.native.company_id,
        work=selected.binding.child.binding,
        registration_sha256=selected.native.registration_hash,
        acceptance_id=record.acceptance_id,
        acceptance_sha256=canonical_sha256(record),
        receipt_id=record.target.receipt_id,
        accepted_at=record.recorded_at,
        receipt_recorded_at=receipt_recorded_at,
        proof_ids=tuple(row.proof_id for row in record.proofs),
        artifacts=(*record.target.artifacts, *(row.result_artifact for row in record.proofs)),
        status="accepted_report",
    )
