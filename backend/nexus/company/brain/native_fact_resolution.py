"""Resolve bounded selectors only from actual native state; no supplied amounts or verdicts."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.native_fact_admission import decision_deadlines
from nexus.company.brain.native_fact_contracts import (
    BlockedSelector,
    CapSelector,
    DecisionSelector,
    DecisionState,
    DigestSelector,
    DigestState,
    FailedReceiptSelector,
    NativeEventSelector,
    NativeEventState,
)
from nexus.company.brain.native_fact_digest import digest_state
from nexus.company.brain.native_fact_inputs import (
    receipt_references,
    source_references,
    work_resources,
)
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.brain.native_fact_work import (
    blocked_state,
    cap_state,
    decision_state,
    failed_receipt_state,
)
from nexus.company.brain.scope_support import BrainDeniedError
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.operating_report_inputs import author_input_references
from nexus.execution.management_checks import require_management_execution
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.journal_submission import pending_action_record


@dataclass(frozen=True)
class ResolvedNativeFact:
    state: NativeEventState
    resource: ResourceRef
    resources: tuple[UUID, ...]
    references: tuple[ArtifactRevisionRef, ...]
    deadlines: tuple[datetime, ...]
    recorded_at: datetime


async def action_resource(
    session: AsyncSession,
    scope: BrainReadScope,
    action_id: UUID,
    services: NativeFactServices,
) -> ResourceRef:
    row = await session.get(JournalAction, action_id)
    if row is None or row.company_id != scope.company_id:
        raise BrainDeniedError("Native event action is unavailable")
    record = pending_action_record(row)
    if record.proposal_hash != action_hash(record.proposal):
        raise BrainDeniedError("Native event action hash is inconsistent")
    reference = next(
        (
            item.resource
            for item in services.catalog.resources
            if item.symbol == record.proposal.resource
        ),
        None,
    )
    if reference is None:
        raise BrainDeniedError("Native event action resource mapping is unavailable")
    return reference


async def resolve_fact(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    selector: NativeEventSelector,
    services: NativeFactServices,
    now: datetime,
) -> ResolvedNativeFact | None:
    state: NativeEventState | None
    if isinstance(selector, DigestSelector):
        state = await digest_state(session, control, scope, identity, selector, services, now)
        return (
            await _digest_inputs(session, control, scope, identity, state, services)
            if state
            else None
        )
    if isinstance(selector, DecisionSelector):
        state = await decision_state(session, control, scope, selector.action_id)
        if state is not None:
            await _current_actor(session, control, state, services)
    elif isinstance(selector, BlockedSelector):
        state = await blocked_state(session, control, scope, identity, selector.task_id, services)
    elif isinstance(selector, CapSelector):
        state = await cap_state(session, control, scope, selector, now)
    elif isinstance(selector, FailedReceiptSelector):
        state = await failed_receipt_state(session, scope, selector.action_id)
    else:
        raise BrainDeniedError("Native event selector is unsupported")
    if state is None:
        return None
    return await _work_inputs(session, scope, state, selector, services, now)


async def _work_inputs(
    session: AsyncSession,
    scope: BrainReadScope,
    state: NativeEventState,
    selector: NativeEventSelector,
    services: NativeFactServices,
    now: datetime,
) -> ResolvedNativeFact:
    task_id = getattr(state, "work", None)
    task_id = task_id.task_id if task_id is not None else getattr(state, "task_id", None)
    resource = (
        await action_resource(session, scope, selector.action_id, services)
        if isinstance(selector, (DecisionSelector, FailedReceiptSelector))
        else services.resource
    )
    resources = (
        await work_resources(session, scope, task_id, services) if task_id is not None else ()
    )
    references = await source_references(session, scope, resources)
    if task_id is not None:
        references = _unique((*references, *await receipt_references(session, scope, task_id)))
    return ResolvedNativeFact(
        state,
        resource,
        tuple(sorted(set(resources) | {resource.resource_id})),
        references,
        await decision_deadlines(session, state, services, now)
        if isinstance(state, DecisionState)
        else (),
        getattr(state, "recorded_at", now),
    )


async def _current_actor(
    session: AsyncSession,
    control: CompanyControl,
    state: DecisionState,
    services: NativeFactServices,
) -> None:
    work = await session.get(ExecutionWork, (control.company_id, state.work.task_id))
    if work is None:
        raise BrainDeniedError("Native pending decision work is unavailable")
    from nexus.company.management.report_input_contracts import native_author

    actor = services.scheduler.identities.actor(native_author(work)[0])
    await require_management_execution(
        session,
        control,
        work,
        actor,
        services.catalog,
        services.artifacts,
        services.freshness,
        state.action.proposal,
        "model_requests" if state.action.proposal.tool == "model.request.v1" else "tool_attempts",
    )


def _unique(references: tuple[ArtifactRevisionRef, ...]) -> tuple[ArtifactRevisionRef, ...]:
    result: dict[UUID, ArtifactRevisionRef] = {}
    for reference in references:
        previous = result.get(reference.artifact_revision_id)
        if previous is not None and previous != reference:
            raise BrainDeniedError("Native fact input revision conflicts")
        result[reference.artifact_revision_id] = reference
    return tuple(result[key] for key in sorted(result))


async def _digest_inputs(
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    identity: VerifiedIdentity,
    state: DigestState,
    services: NativeFactServices,
) -> ResolvedNativeFact:
    references = await author_input_references(
        session, control, scope, identity, state.saved, services.artifacts, services.freshness
    )
    resource = state.registration.resource
    return ResolvedNativeFact(
        state,
        resource,
        tuple(sorted(set(state.saved.data.required_resource_ids) | {resource.resource_id})),
        references,
        (state.registration.expires_at,),
        state.saved.observed_at,
    )
