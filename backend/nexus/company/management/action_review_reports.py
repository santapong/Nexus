"""Actual owner report reads precede the final complete action disclosure transaction."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.sources import ArtifactRevisionRef, EvidenceRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance import VerificationSpec
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.acceptance_support import (
    actual_receipt,
    receipt_artifacts,
    stored_plan,
)
from nexus.company.management.acceptance_targets import current_work
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.generated_artifact_contracts import GeneratedArtifactActionParameters
from nexus.company.management.operating_report_contracts import SavedOperatingReport
from nexus.company.management.operating_report_inputs import author_input_references
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.owner_view_sources import (
    evidence_artifacts,
    owner_brain_scope,
)
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.plans import PlanPayload
from nexus.company.management.transactions import management_owner_transaction
from nexus.harness.journal_models import CompanyControl, JournalAction

GENERATED_TOOLS = {"company.report.write.v1", "company.report.check.v1"}


def action_parameters(proposal: ActionProposal) -> GeneratedArtifactActionParameters:
    return GeneratedArtifactActionParameters.model_validate_json(json.dumps(proposal.parameters))


async def report_selector(
    session: AsyncSession, company_id: UUID, proposal: ActionProposal
) -> UUID:
    parameters = action_parameters(proposal)
    if proposal.tool == "company.report.write.v1":
        require_acceptance(parameters.report_id is not None)
        assert parameters.report_id is not None
        return parameters.report_id
    author = await session.get(JournalAction, parameters.author_action_id)
    require_acceptance(author is not None and author.company_id == company_id)
    assert author is not None
    actual = ActionProposal.model_validate_json(author.proposal_json)
    require_acceptance(actual.tool == "company.report.write.v1")
    pins = action_parameters(actual)
    require_acceptance(pins.report_id is not None)
    assert pins.report_id is not None
    return pins.report_id


async def load_review_report(
    factory: async_sessionmaker[AsyncSession],
    reports: OperatingReportStore | None,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    action_id: UUID,
) -> SavedOperatingReport | None:
    if reports is None:
        return None
    try:
        async with management_owner_transaction(factory, scope, identity, allow_paused=True) as (
            session,
            _,
            _,
        ):
            row = await session.get(JournalAction, action_id)
            if row is None or row.company_id != scope.company_id:
                return None
            proposal = ActionProposal.model_validate_json(row.proposal_json)
            if proposal.tool not in GENERATED_TOOLS:
                return None
            selector = await report_selector(session, scope.company_id, proposal)
        # Public get_saved uses its own CompanyControl transaction; never nest that mutex.
        return await reports.get_saved(scope, identity, selector)
    except ValueError:
        return None


async def report_review_inputs(
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    identity: VerifiedIdentity,
    binding: CurrentPlanBinding,
    proposal: ActionProposal,
    record: SavedOperatingReport | None,
    reports: OperatingReportStore | None,
) -> tuple[tuple[ArtifactRevisionRef, ...], tuple[UUID, ...]]:
    if proposal.tool not in GENERATED_TOOLS:
        return (), ()
    require_acceptance(record is not None and reports is not None)
    assert record is not None and reports is not None
    require_acceptance(
        record.company_id == scope.company_id
        and record.created_by == control.owner_id
        and record.selection.plan == binding.plan
        and record.report_id == await report_selector(session, scope.company_id, proposal)
    )
    for selected in (record.selection.author, record.selection.verifier):
        native = await ManagementPlanStore.current_binding(
            session, scope.company_id, selected.task_id
        )
        require_acceptance(
            native is not None and native.plan == binding.plan and native.child.binding == selected
        )
    parameters = action_parameters(proposal)
    selected = record.selection.author if parameters.report_id else record.selection.verifier
    require_acceptance(binding.child.binding == selected)
    brain = owner_brain_scope(scope, identity)
    references = await author_input_references(
        session, control, brain, identity, record, reports.artifacts, reports.freshness
    )
    citations = await evidence_artifacts(
        session,
        scope,
        tuple(
            EvidenceRef(company_id=scope.company_id, evidence_id=key)
            for key in parameters.evidence_ids
        ),
    )
    require_acceptance(citations is not None)
    assert citations is not None
    target = await check_target_artifacts(session, control, binding, proposal, record)
    values = {row.artifact_revision_id: row for row in (*references, *citations, *target)}
    require_acceptance(0 < len(values) <= 33)
    return tuple(values[key] for key in sorted(values)), record.data.required_resource_ids


async def check_target_artifacts(
    session: AsyncSession,
    control: CompanyControl,
    binding: CurrentPlanBinding,
    proposal: ActionProposal,
    record: SavedOperatingReport,
) -> tuple[ArtifactRevisionRef, ...]:
    if proposal.tool != "company.report.check.v1":
        return ()
    pins = action_parameters(proposal)
    author_binding = await ManagementPlanStore.current_binding(
        session, binding.company_id, record.selection.author.task_id
    )
    require_acceptance(author_binding is not None)
    assert author_binding is not None and pins.author_action_id is not None
    payload = await review_plan(session, binding)
    author, _, _ = await current_work(
        session, control, payload, binding.plan.plan_revision_id, record.selection.author.task_id
    )
    receipt = await actual_receipt(session, author, pins.author_action_id)
    artifacts = await receipt_artifacts(session, receipt)
    edge = next(
        (
            row
            for row in payload.verification
            if row.author_task_id == author.task_id and row.verifier_task_id == proposal.task_id
        ),
        None,
    )
    require_acceptance(edge is not None)
    assert edge is not None
    target = VerificationSpec(
        company_id=binding.company_id,
        author=record.selection.author,
        verifier=record.selection.verifier,
        action_id=pins.author_action_id,
        proposal_sha256=receipt.proposal_hash,
        receipt_id=receipt.receipt_id,
        receipt_sha256=canonical_sha256(receipt),
        work_snapshot_sha256=author.registration_hash,
        criterion_ids=author_binding.work.acceptance,
        artifacts=artifacts,
        check_recipe=edge.check_recipe,
    )
    require_acceptance(canonical_sha256(target) == pins.verification_target_sha256)
    return artifacts


async def review_plan(session: AsyncSession, binding: CurrentPlanBinding) -> PlanPayload:
    row = await session.get(
        ManagementPlanRevision, (binding.company_id, binding.plan.plan_revision_id)
    )
    require_acceptance(row is not None)
    assert row is not None
    return stored_plan(row, binding.company_id)
