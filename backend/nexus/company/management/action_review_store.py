"""Fresh signed-owner disclosure gate; unreadable resources retain only safe action audit."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.action_review_coding import CodingReviewSelection
from nexus.company.management.action_review_contracts import ActionReview, ExactActionDetail
from nexus.company.management.action_review_planning import (
    PlanningReviewInputs,
    PlanningReviewSelection,
)
from nexus.company.management.action_review_reports import load_review_report, report_review_inputs
from nexus.company.management.action_review_resources import (
    action_resource_symbols,
    review_artifacts,
    review_named_artifacts,
)
from nexus.company.management.control_support import db_clock, require_member
from nexus.company.management.operating_report_contracts import SavedOperatingReport
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.owner_view_approvals import action_audit
from nexus.company.management.owner_view_contracts import ApprovalView
from nexus.company.management.owner_view_sources import (
    OwnerViewSources,
    SourceDisclosure,
    owner_brain_scope,
    source_disclosure,
)
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding, PlanAdmissionCatalog
from nexus.company.management.planning_native_facts import clock_us, read_end, require_time
from nexus.company.management.planning_prepared_store import PlanningPreparedStore
from nexus.company.management.revision_store import require_current_governance
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.coding_owner_reads import CodingOwnerReader
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction


@dataclass(frozen=True, slots=True)
class ReviewedAction:
    """Descriptive private READ cutoff; no field is a source/effect permit."""

    value: ActionReview
    read_end_us: int


class OwnerActionReviewStore:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        catalog: PlanAdmissionCatalog,
        sources: OwnerViewSources,
        reports: OperatingReportStore | None = None,
        *,
        planning: PlanningPreparedStore | None = None,
        coding: CodingOwnerReader | None = None,
    ) -> None:
        self.factory, self.catalog, self.sources = factory, catalog, sources
        self.reports, self.planning = reports, planning
        self._planning_inputs = (
            PlanningReviewInputs(factory, catalog, sources, planning)
            if planning is not None
            else None
        )
        self._original_planning = self._planning_inputs
        self.coding, self._original_coding = coding, coding
        self._coding()

    def _planning(self) -> PlanningReviewInputs | None:
        value = self._planning_inputs
        if (
            value is not self._original_planning
            or (
                value is not None
                and (
                    self.planning is not value.store
                    or self.factory is not value.factory
                    or self.catalog is not value.catalog
                    or self.sources is not value.sources
                )
            )
            or (value is None and self.planning is not None)
        ):
            raise ManagementDeniedError("Original planning action review composition changed")
        if value is not None:
            value.require_composition()
        return value

    def _coding(self) -> CodingOwnerReader | None:
        value = self.coding
        if value is not self._original_coding or (
            value is not None
            and (
                type(value) is not CodingOwnerReader
                or value.services.factory is not self.factory
                or value.services.management.catalog is not self.catalog
                or value.services.source_views.artifacts is not self.sources.artifacts
                or value.services.source_views.freshness is not self.sources.freshness
            )
        ):
            raise ManagementDeniedError("Original coding action review composition changed")
        if value is not None:
            value.require_composition()
        return value

    def pending_owners(self) -> tuple[asyncio.Task[object], ...]:
        """Actual C owner read leaves stay reachable through the configured review service."""
        coding = self._coding()
        planning = self._planning()
        return tuple(
            dict.fromkeys(
                (
                    *(coding.pending_owners() if coding else ()),
                    *(planning.store.pending_owners() if planning else ()),
                    *(planning.store.blobs.pending_owners() if planning else ()),
                )
            )
        )

    async def review(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
    ) -> ActionReview:
        """Preserve the legacy data-only API; HTTP uses the descriptive cutoff too."""
        result = await self.read(scope, identity, action_id, end_us=read_end())
        require_time(result.read_end_us)
        return result.value

    async def read(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
        *,
        end_us: int,
        credential: AuthenticatedWorkerIdentity | None = None,
    ) -> ReviewedAction:
        """One original caller end includes all metadata, private I/O and transaction exits."""
        end_us = read_end(end_us)
        async with asyncio.timeout(max(0, end_us - clock_us()) / 1_000_000):
            result = await self._read(scope, identity, action_id, end_us, credential)
        require_time(result.read_end_us)
        return result

    async def _read(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
        end_us: int,
        credential: AuthenticatedWorkerIdentity | None = None,
    ) -> ReviewedAction:
        # Cohesion exception: first metadata gate, out-of-lock protected read and
        # final native/source gate must remain visibly ordered under one cutoff.
        planning = self._planning()
        coding = self._coding()
        selected_coding: CodingReviewSelection | None = None
        record = await load_review_report(self.factory, self.reports, scope, identity, action_id)
        selected: PlanningReviewSelection | None = None
        first_static: SourceDisclosure | None = None
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (session, control, _):
            row = await _row(session, scope, action_id)
            audit = await action_audit(session, row)
            admitted = None
            try:
                proposal, work, binding = await current_review_work(session, control, scope, row)
                is_planning = work.workflow_name == "company.planning.v1" or any(
                    condition.resource.startswith("planning.prepared:")
                    for condition in proposal.preconditions
                )
                is_coding = work.workflow_name == "company.coding.v1" or any(
                    condition.resource.startswith("coding.prepared:")
                    for condition in proposal.preconditions
                )
                if is_coding:
                    # Reserved C data never falls back to generic catalog aliases.
                    if coding is not None and credential is not None:
                        if credential.identity != identity:
                            raise ManagementDeniedError("Original coding owner identity changed")
                        selected_coding = await coding.select_locked(
                            session,
                            control,
                            scope,
                            credential,
                            proposal,
                            work,
                            binding,
                            end_us=end_us,
                        )
                        end_us = min(end_us, selected_coding.read_end_us)
                elif is_planning:
                    if planning is not None:
                        selected = planning.select(control, proposal, work, binding)
                        refs, ids = await _planning_artifacts(
                            session, binding, proposal, self.catalog
                        )
                        first_static = await review_disclosure(
                            session, control, scope, identity, self.sources, refs, ids
                        )
                        if first_static is None:
                            selected = None
                else:
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
            except ValueError:
                selected = None
            anchor = clock_us()
            now = await db_clock(session)
            if (
                selected is not None
                and first_static is not None
                and first_static.valid_until is not None
            ):
                # Static charter/target inputs may be outside the prepared manifest.
                # Retain this original window before releasing CC; refresh cannot renew it.
                end_us = min(
                    end_us,
                    anchor + (first_static.valid_until - now) // timedelta(microseconds=1),
                )
            result = _result(scope, audit, admitted, now, anchor, end_us)
        require_time(end_us)
        if selected_coding is not None and coding is not None and credential is not None:
            try:
                actual = await coding.review_selected(
                    scope, credential, action_id, selected_coding, end_us=end_us
                )
            except TimeoutError:
                raise
            except (ValueError, OSError):
                require_time(end_us)
                return result
            self._coding()
            require_time(actual.read_end_us)
            return ReviewedAction(actual.value, actual.read_end_us)
        if selected is None or planning is None:
            return result
        # load_owner takes its own CompanyControl mutex; never call it inside the TX above.
        try:
            loaded = await planning.load(scope, identity, action_id, end_us=end_us)
        except ValueError:
            return result  # Safe audit only; no partial private result is adopted.
        end_us = min(end_us, loaded.read_end_us)
        async with management_owner_transaction(
            self.factory, scope, identity, allow_paused=True
        ) as (session, control, _):
            row = await _row(session, scope, action_id)
            audit = await action_audit(session, row)
            admitted = None
            try:
                self._planning()
                proposal, work, binding = await current_review_work(session, control, scope, row)
                end_us = await planning.validate(
                    session,
                    control,
                    scope,
                    identity,
                    proposal,
                    work,
                    binding,
                    selected,
                    loaded,
                    end_us=end_us,
                )
                refs, ids = await _planning_artifacts(session, binding, proposal, self.catalog)
                disclosure = await review_disclosure(
                    session, control, scope, identity, self.sources, refs, ids
                )
                await _final_review_reads(session, control, work)
                if disclosure is not None:
                    admitted = (
                        ExactActionDetail(
                            company_id=scope.company_id,
                            task_id=work.task_id,
                            trace_id=work.trace_id,
                            run_id=work.run_id,
                            proposal_sha256=row.proposal_hash,
                            proposal=proposal,
                        ),
                        disclosure,
                    )
            except ValueError:
                admitted = None
            anchor = clock_us()
            now = await db_clock(session)
            result = _result(scope, audit, admitted, now, anchor, end_us)
        self._planning()
        require_time(result.read_end_us)
        return result


async def _row(session: AsyncSession, scope: CompanyControlScope, action_id: UUID) -> JournalAction:
    row = await session.get(JournalAction, action_id)
    if row is None or row.company_id != scope.company_id:
        raise ManagementDeniedError("Action review is unavailable")
    return row


async def _planning_artifacts(
    session: AsyncSession,
    binding: CurrentPlanBinding,
    proposal: ActionProposal,
    catalog: PlanAdmissionCatalog,
) -> tuple[tuple[ArtifactRevisionRef, ...], tuple[UUID, ...]]:
    symbols = await action_resource_symbols(session, binding, proposal, catalog)
    return await review_named_artifacts(session, binding, proposal, catalog, symbols)


def _result(
    scope: CompanyControlScope,
    audit: ApprovalView,
    admitted: tuple[ExactActionDetail, SourceDisclosure] | None,
    now: datetime,
    anchor: int,
    end_us: int,
) -> ReviewedAction:
    detail = admitted[0] if admitted is not None and admitted[1].permits(now) else None
    if detail is not None and admitted is not None and admitted[1].valid_until is not None:
        end_us = min(end_us, anchor + (admitted[1].valid_until - now) // timedelta(microseconds=1))
    value = ActionReview(
        company_id=scope.company_id,
        observed_at=now,
        audit=audit,
        availability="available" if detail is not None else "unavailable",
        detail=detail,
    )
    require_time(end_us)
    return ReviewedAction(value, end_us)


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
