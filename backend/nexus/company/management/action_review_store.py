"""Fresh signed-owner disclosure gate; unreadable resources retain only safe action audit."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.action_review_contracts import ActionReview, ExactActionDetail
from nexus.company.management.action_review_reports import load_review_report, report_review_inputs
from nexus.company.management.action_review_resources import review_artifacts
from nexus.company.management.control_support import db_clock, require_member
from nexus.company.management.operating_report_contracts import SavedOperatingReport
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.owner_view_approvals import action_audit
from nexus.company.management.owner_view_sources import (
    OwnerViewSources,
    SourceDisclosure,
    owner_brain_scope,
    source_disclosure,
)
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding, PlanAdmissionCatalog
from nexus.company.management.revision_store import require_current_governance
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction


class OwnerActionReviewStore:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        catalog: PlanAdmissionCatalog,
        sources: OwnerViewSources,
        reports: OperatingReportStore | None = None,
    ) -> None:
        self.factory, self.catalog, self.sources = factory, catalog, sources
        self.reports = reports

    async def review(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
    ) -> ActionReview:
        record = await load_review_report(self.factory, self.reports, scope, identity, action_id)
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (
            session,
            control,
            _,
        ):
            row = await session.get(JournalAction, action_id)
            if row is None or row.company_id != scope.company_id:
                raise ManagementDeniedError("Action review is unavailable")
            audit = await action_audit(session, row)
            admitted = await _detail(
                session,
                control,
                scope,
                identity,
                row,
                self.catalog,
                self.sources,
                record,
                self.reports,
            )
            now = await db_clock(session)
            detail = admitted[0] if admitted is not None and admitted[1].permits(now) else None
            return ActionReview(
                company_id=scope.company_id,
                observed_at=now,
                audit=audit,
                availability="available" if detail is not None else "unavailable",
                detail=detail,
            )


async def _detail(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    row: JournalAction,
    catalog: PlanAdmissionCatalog,
    sources: OwnerViewSources,
    record: SavedOperatingReport | None,
    reports: OperatingReportStore | None,
) -> tuple[ExactActionDetail, SourceDisclosure] | None:
    try:
        proposal, work, binding = await current_review_work(session, control, scope, row)
        refs, resources = await review_artifacts(session, binding, proposal, catalog)
        report_refs, report_resources = await report_review_inputs(
            session, control, scope, identity, binding, proposal, record, reports
        )
        refs = tuple(
            {value.artifact_revision_id: value for value in (*refs, *report_refs)}.values()
        )
        disclosure = await review_disclosure(
            session,
            control,
            scope,
            identity,
            sources,
            refs,
            tuple(sorted(set(resources) | set(report_resources))),
        )
        if disclosure is None:
            return None
        await _final_review_reads(session, control, work)
        if not disclosure.permits(await db_clock(session)):
            return None
        return ExactActionDetail(
            company_id=scope.company_id,
            task_id=work.task_id,
            trace_id=work.trace_id,
            run_id=work.run_id,
            proposal_sha256=row.proposal_hash,
            proposal=proposal,
        ), disclosure
    except ValueError:
        return None


async def current_review_work(
    session: AsyncSession, control: CompanyControl, scope: CompanyControlScope, row: JournalAction
) -> tuple[ActionProposal, ExecutionWork, CurrentPlanBinding]:
    proposal = ActionProposal.model_validate_json(row.proposal_json)
    if len(json.dumps(proposal.parameters, ensure_ascii=False).encode()) > 16384 or (
        proposal.policy_version,
        proposal.price_version,
        action_hash(proposal),
    ) != (control.policy_version, control.price_version, row.proposal_hash):
        raise ManagementDeniedError("Exact proposal is unavailable")
    work = await session.get(ExecutionWork, (scope.company_id, row.task_id))
    binding = await ManagementPlanStore.current_binding(session, scope.company_id, row.task_id)
    if (
        work is None
        or binding is None
        or (work.trace_id, work.actor_id) != (proposal.trace_id, proposal.actor_id)
    ):
        raise ManagementDeniedError("Exact native work is unavailable")
    await require_member(session, control, work.actor_id)
    await require_current_governance(session, control, binding.plan, binding.child)
    return proposal, work, binding


async def review_disclosure(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    sources: OwnerViewSources,
    references: tuple[ArtifactRevisionRef, ...],
    resources: tuple[UUID, ...],
) -> SourceDisclosure | None:
    disclosure = await source_disclosure(session, control, scope, identity, sources, references)
    if disclosure is None:
        return None
    grants = await require_resources(
        session, owner_brain_scope(scope, identity), resources, await db_clock(session)
    )
    expiries = [value.expires_at for value in grants if value.expires_at is not None]
    if disclosure.valid_until is not None:
        expiries.append(disclosure.valid_until)
    return SourceDisclosure(min(expiries) if expiries else None)


async def _final_review_reads(
    session: AsyncSession, control: CompanyControl, work: ExecutionWork
) -> None:
    await require_member(session, control, work.actor_id)
