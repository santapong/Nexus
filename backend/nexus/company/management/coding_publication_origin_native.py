"""Concrete read-only native/publication joins; no DTO or helper grants READ or intent.

Cohesion exception: original C receipt/whole-proof and exact current pair rows
share one closed metadata comparison. Actual IO/issued proof stays in the reader.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.execution_contracts import BuilderExecutionSpec
from nexus.company.brain.access_support import require_resources
from nexus.company.brain.artifact_input_models import BrainArtifactInput
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.native_fact_inputs import source_artifact_reference
from nexus.company.brain.source_models import (
    BrainSource,
    BrainSourceHead,
    BrainSourceRevision,
)
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.directory_models import DirectoryMembership
from nexus.company.management.acceptance_provenance import reference_sources
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_prepared_checks import (
    action_sources,
    require_action_header,
    root_registration,
    shorten,
)
from nexus.company.management.coding_prepared_contracts import header_reference, prepared_reference
from nexus.company.management.coding_publication_contracts import (
    CodingModelOrigin,
)
from nexus.company.management.cycle_cost_contracts import NativeCostSelection
from nexus.company.management.cycle_model_reader import native_cost_selection
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.nexus_coding_catalog import coding_work_matches_template
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.planning_native_facts import clock_us
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.management_checks import require_management_execution
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_support import (
    db_now,
    execution_row,
    lease_scope,
    registration_digest,
    require_lease,
)
from nexus.harness.canonical import action_hash
from nexus.harness.journal_budget import billing_day
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.lifecycle import ActionState
from nexus.harness.model_authorizer_contracts import model_action_recipe_hash

if TYPE_CHECKING:
    from nexus.company.management.coding_publication_origin import CodingPublicationOriginReader


@dataclass(frozen=True, slots=True)
class OriginSelection:
    native: NativeCostSelection
    references: tuple[ArtifactRevisionRef, ...]
    inputs: tuple[ArtifactRevisionRef, ...]
    end_us: int
    owner_id: UUID
    source_signature: str
    root_registration_sha256: str
    plan: PlanRevisionRef


def require_c_native(
    reader: CodingPublicationOriginReader, native: NativeCostSelection, owner: UUID
) -> None:
    """Known corrupt native IDs deny before derivative bytes; no billing/READ permit.

    Cohesion exception: the complete actual action/attempt/intent/receipt/hold
    identity is one comparison, before the header-dependent whole-proof join.
    """
    action, intent, held, attempt = native.action, native.intent, native.hold, native.attempt
    work, slot = native.directory.work, reader.admission.slots[1]
    bound, approval = slot.child.binding, action.approval
    if (
        work is None
        or intent is None
        or intent.receipt is None
        or held is None
        or attempt is None
        or approval is None
    ):
        raise ValueError("Coding native result is incomplete")
    call, receipt = action.proposal, intent.receipt
    if len(receipt.artifacts) != 1:
        raise ValueError("Coding native result has no exact envelope")
    artifact = receipt.artifacts[0]
    import json

    from nexus.company.management.planning_prepared_contracts import PlanningModelParameters

    parameters = PlanningModelParameters.model_validate_json(json.dumps(call.parameters))
    expected = (bound.company_id, bound.task_id, bound.trace_id, call.action_id)
    if (
        call.action_id != reader.rules.action_id
        or parameters.attempt_id != call.action_id
        or parameters.registry_id != slot.tool.resource.removeprefix("model:")
        or parameters.registry_revision != bound.model_registry_version
        or (call.company_id, call.task_id, call.trace_id, call.action_id) != expected
        or call.actor_id != bound.actor_id
        or (call.tool, call.tool_version, call.resource)
        != (slot.tool.tool, slot.tool.tool_version, slot.tool.resource)
        or action_hash(call) != action.proposal_hash
        or action.state != ActionState.AUTHORIZED
        or action.consumed_at is None
        or approval.decision != "approved"
        or (
            approval.company_id,
            approval.action_id,
            approval.action_revision,
            approval.action_hash,
            approval.approver_id,
        )
        != (bound.company_id, call.action_id, call.revision, action.proposal_hash, owner)
        or not approval.issued_at <= action.consumed_at <= intent.created_at < approval.expires_at
        or (
            intent.company_id,
            intent.task_id,
            intent.trace_id,
            intent.action_id,
            intent.run_id,
            intent.proposal_hash,
            intent.attempt_kind,
            intent.state,
        )
        != (*expected, bound.run_id, action.proposal_hash, "model_requests", "succeeded")
        or (
            receipt.company_id,
            receipt.task_id,
            receipt.trace_id,
            receipt.action_id,
            receipt.proposal_hash,
            receipt.receipt_id,
            receipt.outcome,
        )
        != (*expected, action.proposal_hash, uuid5(call.action_id, "model-receipt-v1"), "succeeded")
        or (
            attempt.company_id,
            attempt.task_id,
            attempt.trace_id,
            attempt.attempt_id,
            attempt.kind,
            attempt.fence,
            attempt.reserved_at,
        )
        != (*expected, "model_requests", intent.intent_fence, intent.created_at)
        or (held.company_id, held.task_id, held.action_id, held.day, held.amount_usd, held.state)
        != (
            bound.company_id,
            bound.task_id,
            call.action_id,
            billing_day(intent.created_at),
            call.estimated_cost_usd,
            "reconciled",
        )
        or (
            artifact.company_id,
            artifact.artifact_id,
            artifact.revision,
            artifact.allowed_principals,
        )
        != (
            bound.company_id,
            uuid5(call.action_id, str(parameters.request_id)),
            "model-result-envelope-v1",
            (bound.actor_id, owner),
        )
        or not coding_work_matches_template(work.registration.work, slot.work)
        or work.registration.quota != slot.child.quota
        or (
            work.registration.run_id,
            work.registration.workflow_name,
            work.registration.workflow_version,
            work.registration.model_profile,
            work.registration.model_registry_version,
        )
        != (
            bound.run_id,
            bound.workflow_name,
            bound.workflow_version,
            bound.model_profile,
            bound.model_registry_version,
        )
        or (
            native.directory.company_id,
            native.directory.task_id,
            native.directory.trace_id,
            native.directory.actor_id,
            native.directory.workspace_id,
            native.directory.root_task_id,
            native.directory.parent_task_id,
        )
        != (
            bound.company_id,
            bound.task_id,
            bound.trace_id,
            bound.actor_id,
            bound.workspace_id,
            reader.admission.procedure.binding.task_id,
            reader.admission.procedure.binding.task_id,
        )
        or not native.directory.active
        or held.actual_usd is None
    ):
        raise ValueError("Actual native C action/approval/receipt/attempt/hold identity differs")


async def origin_references(
    reader: CodingPublicationOriginReader,
    session: AsyncSession,
    control: CompanyControl,
    scope: BrainReadScope,
    credential: AuthenticatedWorkerIdentity,
    end_us: int,
) -> tuple[ArtifactRevisionRef, ...]:
    refs = []
    for registration, policy in (
        (reader.rules.origin, reader.rules.origin_policy),
        (reader.rules.patch, reader.rules.patch_policy),
    ):
        source = await reader._checked(
            session.get(BrainSource, (control.company_id, registration.source_id)),
            credential,
            end_us,
        )
        head = await reader._checked(
            session.get(BrainSourceHead, (control.company_id, registration.source_id)),
            credential,
            end_us,
        )
        revision = (
            await reader._checked(
                session.get(BrainSourceRevision, (control.company_id, head.current_revision_id)),
                credential,
                end_us,
            )
            if head
            else None
        )
        if (
            source is None
            or head is None
            or revision is None
            or (
                (
                    source.resource_id,
                    source.source_symbol,
                    source.external_key,
                    source.authority_profile,
                    source.data_classification,
                    source.recorded_by,
                )
                != (
                    registration.resource.resource_id,
                    registration.source_symbol,
                    registration.external_key,
                    policy.authority_profile,
                    policy.data_classification,
                    control.owner_id,
                )
            )
            or (revision.source_id != source.source_id)
            or (revision.recorded_by != control.owner_id)
            or (head.availability != "available")
        ):
            raise ValueError("Actual current registered J source pair is unavailable")
        refs.append(
            await reader._checked(
                source_artifact_reference(session, scope, revision.artifact_revision_id),
                credential,
                end_us,
            )
        )
    return tuple(refs)


async def read_origin_selection(
    reader: CodingPublicationOriginReader,
    session: AsyncSession,
    control: CompanyControl,
    lease: ExecutionLease,
    credential: AuthenticatedWorkerIdentity,
    spec: BuilderExecutionSpec,
    end_us: int,
) -> OriginSelection:
    from nexus.company.management.coding_publication_origin import coding_scope

    reader._role(lease, credential)
    reader._current(credential, end_us)
    scope = coding_scope(lease, credential, spec.job.action_id)
    work = await reader._checked(execution_row(session, lease_scope(lease)), credential, end_us)
    require_lease(
        work, lease, await reader._checked(db_now(session), credential, end_us), execute=True
    )
    action = await reader._checked(
        session.get(JournalAction, spec.job.action_id), credential, end_us
    )
    if action is None:
        raise ValueError("Actual E/EV action is unavailable")
    from nexus.company.contracts.actions import ActionProposal

    proposal = ActionProposal.model_validate_json(action.proposal_json)
    if (
        proposal.parameters != spec.model_dump(mode="json")
        or action_hash(proposal) != action.proposal_hash
    ):
        raise ValueError("Actual E/EV proposal/spec differs")
    await reader._checked(
        require_management_execution(
            session,
            control,
            work,
            credential.identity,
            reader.catalog,
            reader.artifacts,
            reader.freshness,
            proposal,
            "tool_attempts",
        ),
        credential,
        end_us,
    )
    native = await reader._checked(
        native_cost_selection(session, lease.company_id, reader.rules.action_id), credential, end_us
    )
    coder = reader.admission.slots[1]
    current = native.directory.work
    intent, held, approval = (native.intent, native.hold, native.action.approval)
    owner = await reader._checked(
        session.get(DirectoryMembership, (control.company_id, control.owner_id)), credential, end_us
    )
    if (
        control.paused
        or owner is None
        or (not owner.principal_active)
        or (not owner.membership_active)
        or (owner.role != "owner")
        or (current is None)
        or (intent is None)
        or (held is None)
        or (approval is None)
        or (native.action.proposal.actor_id != coder.child.binding.actor_id)
        or not coding_work_matches_template(current.registration.work, coder.work)
        or (current.registration.run_id != coder.child.binding.run_id)
        or (current.state != "verifying")
        or (current.worker_id is not None)
        or (current.expires_at is not None)
        or (current.fence <= intent.intent_fence)
        or (current.counters.model_requests != 1)
        or (intent.state != "succeeded")
        or (intent.verification is not None)
        or (intent.receipt is None)
        or (intent.receipt.outcome != "succeeded")
        or (len(intent.receipt.artifacts) != 1)
        or (held.state != "reconciled")
        or (held.actual_usd is None)
        or (approval.approver_id != control.owner_id)
    ):
        raise ValueError(
            "Published patch requires actual known released C and its current original owner"
        )
    require_c_native(reader, native, control.owner_id)
    signature, c_windows = await reader._checked(
        action_sources(
            session,
            control,
            scope,
            credential.identity,
            native.action.proposal,
            reader.sources,
            historical=False,
        ),
        credential,
        end_us,
    )
    root_sha = await reader._checked(
        root_registration(session, reader.admission), credential, end_us
    )
    binding = await reader._checked(
        ManagementPlanStore.current_binding(session, lease.company_id, coder.work.task_id),
        credential,
        end_us,
    )
    if binding is None:
        raise ValueError("Original C approved plan binding is unavailable")
    if current.registration.work != binding.work:
        raise ValueError("Original C native work differs from its exact approved work")
    refs = await reader._checked(
        origin_references(reader, session, control, scope, credential, end_us), credential, end_us
    )
    if len(refs) != 2 or spec.protected_patch != refs[1]:
        raise ValueError("Builder protected patch differs from actual J publication")
    for ref in refs:
        await reader._checked(
            reader.artifacts.revalidate_artifact_reference(
                session,
                control,
                scope,
                credential.identity,
                ref,
                await reader._checked(db_now(session), credential, end_us),
            ),
            credential,
            end_us,
        )
    await reader._checked(
        reader.freshness.revalidate_references(
            session, scope, refs, await reader._checked(db_now(session), credential, end_us)
        ),
        credential,
        end_us,
    )
    ids, resources = await reader._checked(
        reference_sources(session, scope, refs), credential, end_us
    )
    grants = await reader._checked(
        require_resources(
            session, scope, resources, await reader._checked(db_now(session), credential, end_us)
        ),
        credential,
        end_us,
    )
    windows = [lease.expires_at, credential.expires_at, *c_windows]
    windows.extend(row.expires_at for row in grants if row.expires_at is not None)
    for key in ids:
        head = await reader._checked(
            session.get(BrainSourceHead, (scope.company_id, key)), credential, end_us
        )
        if head is None:
            raise ValueError("Published source closure is incomplete")
        if head.fresh_until is not None:
            windows.append(head.fresh_until)
    inputs = []
    keys = (
        await reader._checked(
            session.scalars(
                select(BrainArtifactInput.input_artifact_revision_id).where(
                    BrainArtifactInput.company_id == scope.company_id,
                    BrainArtifactInput.artifact_revision_id == refs[0].artifact_revision_id,
                )
            ),
            credential,
            end_us,
        )
    ).all()
    if not 1 <= len(keys) <= 33 or len(set(keys)) != len(keys):
        raise ValueError("Published origin has no exact bounded original artifact closure")
    for key in sorted(keys):
        inputs.append(
            await reader._checked(
                source_artifact_reference(session, scope, key), credential, end_us
            )
        )
    before = clock_us()
    final = await reader._checked(db_now(session), credential, end_us)
    end_us = shorten(end_us, before, final, tuple(windows))
    reader._current(credential, end_us)
    return OriginSelection(
        native, refs, tuple(inputs), end_us, control.owner_id, signature, root_sha, binding.plan
    )


def require_origin_native(
    reader: CodingPublicationOriginReader,
    origin: CodingModelOrigin,
    selected: OriginSelection,
    spec: BuilderExecutionSpec,
) -> None:
    """Exact durable native provenance; no raw model read or owner identity is borrowed."""
    native, header = selected.native, origin.header
    action, work, intent, hold, attempt = (
        native.action,
        native.directory.work,
        native.intent,
        native.hold,
        native.attempt,
    )
    assert (
        work is not None and intent is not None and hold is not None and intent.receipt is not None
    )
    receipt = intent.receipt
    artifact = receipt.artifacts[0]
    reference, _ = header_reference(header)
    require_action_header(action.proposal, header)
    models = tuple(
        row
        for row in reader.catalog.models.models
        if row.registry_id == header.parameters.registry_id
    )
    if len(models) != 1:
        raise ValueError("Original C registry model is unavailable")
    model = models[0]
    approval = action.approval
    if (
        prepared_reference(action.proposal) != reference
        or header.plan != selected.plan
        or header.root_registration_sha256 != selected.root_registration_sha256
        or header.input_recipe_sha256 != canonical_sha256(reader.recipe)
        or header.parameters.input_recipe_hash != model_action_recipe_hash(reader.recipe)
        or (header.parameters.input_recipe_id, header.parameters.input_recipe_revision)
        != (reader.recipe.recipe_id, reader.recipe.revision)
        or header.parameters.registry_revision != reader.catalog.models.revision
        or action.state != ActionState.AUTHORIZED
        or action_hash(action.proposal) != action.proposal_hash
        or (
            receipt.company_id,
            receipt.action_id,
            receipt.task_id,
            receipt.trace_id,
            receipt.proposal_hash,
            receipt.receipt_id,
        )
        != (
            header.company_id,
            header.action_id,
            header.task_id,
            header.trace_id,
            action.proposal_hash,
            uuid5(header.action_id, "model-receipt-v1"),
        )
        or (artifact.company_id, artifact.artifact_id)
        != (header.company_id, uuid5(header.action_id, str(header.parameters.request_id)))
        or (hold.company_id, hold.task_id, hold.action_id, hold.day)
        != (header.company_id, header.task_id, header.action_id, billing_day(intent.created_at))
        or (
            approval is not None
            and (
                approval.company_id,
                approval.action_id,
                approval.action_revision,
                approval.action_hash,
            )
            != (
                header.company_id,
                header.action_id,
                action.proposal.revision,
                action.proposal_hash,
            )
        )
        or header.owner_id != selected.owner_id
        or header.admission_sha256 != canonical_sha256(reader.admission)
        or header.goal != reader.admission.goal
        or header.registry_sha256 != canonical_sha256(reader.catalog.models)
        or header.model_sha256 != canonical_sha256(model)
        or origin.price != model.price
        or (origin.provider, origin.api_family, origin.model_id)
        != (model.provider, model.api_family, model.model_id)
        or (
            header.task_id,
            header.trace_id,
            header.actor_id,
            header.workspace_id,
            header.run_id,
        )
        != (
            work.registration.work.task_id,
            work.registration.work.trace_id,
            work.actor_id,
            work.workspace_id,
            work.registration.run_id,
        )
        or header.registration_sha256 != registration_digest(work.registration)
        or (header.root_task_id, header.root_run_id, header.procedure_id)
        != (
            reader.admission.procedure.binding.task_id,
            reader.admission.procedure.binding.run_id,
            reader.admission.procedure.procedure_id,
        )
        or (
            origin.native_proposal_sha256,
            origin.intent_fence,
            origin.intent_created_at,
            origin.receipt_id,
            origin.receipt_sha256,
            origin.model_artifact_id,
            origin.model_artifact_sha256,
            origin.actual_usd,
            origin.day,
        )
        != (
            action.proposal_hash,
            intent.intent_fence,
            intent.created_at,
            receipt.receipt_id,
            canonical_sha256(receipt),
            artifact.artifact_id,
            artifact.sha256,
            hold.actual_usd,
            hold.day,
        )
        or intent.run_id != header.run_id
        or intent.proposal_hash != action.proposal_hash
        or attempt is None
        or (
            attempt.company_id,
            attempt.task_id,
            attempt.trace_id,
            attempt.attempt_id,
            attempt.kind,
            attempt.fence,
            attempt.reserved_at,
        )
        != (
            header.company_id,
            header.task_id,
            header.trace_id,
            header.action_id,
            "model_requests",
            intent.intent_fence,
            intent.created_at,
        )
        or (artifact.company_id, artifact.revision, artifact.allowed_principals)
        != (header.company_id, "model-result-envelope-v1", (header.actor_id, header.owner_id))
        or approval is None
        or approval.decision != "approved"
        or action.consumed_at is None
        or not approval.issued_at <= action.consumed_at <= intent.created_at < approval.expires_at
        or hold.amount_usd != action.proposal.estimated_cost_usd
        or spec.job.source != header.repository_source
        or spec.job.write_paths != header.allowed_write_paths
        or spec.job.patch_sha256 != selected.references[1].sha256
    ):
        raise ValueError(
            "Actual publication/native C/model/request/whole proof or builder source differs"
        )
