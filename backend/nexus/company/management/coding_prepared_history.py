"""Current owner-only C financial header proof, without old execution freshness.

Historical ACL/policy and actual immutable native/root/all-nine-parameter bindings
precede private header I/O. No old C credential, body read, or model eligibility.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_prepared_checks import (
    action_sources,
    require_action_header,
    require_code_metadata,
    root_registration,
    shorten,
)
from nexus.company.management.coding_prepared_contracts import (
    CodingHeaderRead,
    CodingPreparedHeader,
    decode_header,
    prepared_reference,
)
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.owner_view_sources import owner_brain_scope
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.plan_registration import registration
from nexus.company.management.planning_native_facts import clock_us
from nexus.company.management.revision_store import plan_record
from nexus.company.management.transactions import (
    ManagementDeniedError,
    management_owner_transaction,
)
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.execution.runtime_support import db_now, registration_digest
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl

if TYPE_CHECKING:
    from nexus.company.management.coding_prepared_store import CodingPreparedStore
    from nexus.company.management.cycle_cost_contracts import NativeCostSelection


async def validate_history_locked(
    store: CodingPreparedStore,
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    credential: AuthenticatedWorkerIdentity,
    action_id: UUID,
    *,
    header: CodingPreparedHeader | None = None,
    end_us: int,
) -> tuple[NativeCostSelection, str, int]:
    """Requery actual history/source facts in the caller's SAME CC transaction.

    No private bytes, fresh C credential, Goal/head freshness or nested transaction
    is acquired. These descriptive facts cannot grant execution or a new read end.
    """
    from nexus.company.management.cycle_model_reader import (
        native_cost_selection,
        stored_coding_profile,
    )

    store._current(credential, end_us)
    if not session.in_transaction():
        raise ManagementDeniedError("Coding history requires the actual current transaction")
    end = end_us
    brain = owner_brain_scope(scope, credential.identity)
    admission = store.management.catalog.nexus_coding_admission
    assert admission is not None
    selected = await native_cost_selection(session, scope.company_id, action_id)
    action, slot = selected.action.proposal, admission.slots[1]
    if (
        scope.principal_id != credential.identity.principal_id
        or control.owner_id != scope.principal_id
        or selected.directory.work is None
        or selected.directory.work.registration
        != registration(slot.child.binding, slot.work, slot.child.quota)
        or action_hash(action) != selected.action.proposal_hash
        or selected.directory.root_task_id != admission.procedure.binding.task_id
        or selected.directory.parent_task_id != admission.procedure.binding.task_id
        or not await stored_coding_profile(session, admission)
    ):
        raise ManagementDeniedError("Coding historical native/root/owner profile differs")
    root_hash = await root_registration(session, admission, historical=True)
    signature, windows = await action_sources(
        session,
        control,
        brain,
        credential.identity,
        action,
        store.sources,
        historical=True,
    )
    if header is not None:
        require_action_header(action, header)
        await require_code_metadata(session, brain, header)
        original_plan = await session.get(
            ManagementPlanRevision, (scope.company_id, header.plan.plan_revision_id)
        )
        if original_plan is None:
            raise ManagementDeniedError("Coding historical plan is unavailable")
        plan = plan_record(original_plan)
        actual_ref = PlanRevisionRef.model_validate(
            {name: getattr(plan, name) for name in PlanRevisionRef.model_fields}
        )
        if (
            actual_ref != header.plan
            or plan.sha256 != canonical_sha256(plan.payload)
            or plan.payload.coding_admission_sha256 != header.admission_sha256
            or (header.task_id, header.trace_id, header.actor_id, header.workspace_id)
            != (
                action.task_id,
                action.trace_id,
                action.actor_id,
                selected.directory.workspace_id,
            )
        ):
            raise ManagementDeniedError("Coding historical plan/actor/workspace differs")
        if (
            selected.action.approval is None
            or header.owner_id != selected.action.approval.approver_id
            or header.registration_sha256
            != registration_digest(selected.directory.work.registration)
            or (
                header.root_task_id,
                header.root_run_id,
                header.root_registration_sha256,
                header.procedure_id,
            )
            != (
                admission.procedure.binding.task_id,
                admission.procedure.binding.run_id,
                root_hash,
                admission.procedure.procedure_id,
            )
            or header.admission_sha256 != canonical_sha256(admission)
            or header.goal != admission.goal
            or header.input_recipe_sha256 != canonical_sha256(store.recipe)
            or header.run_id != selected.directory.work.registration.run_id
        ):
            raise ManagementDeniedError(
                "Coding historical header differs from actual issued native history"
            )
    before, now = clock_us(), await db_now(session)
    cutoff = shorten(end, before, now, (*windows, credential.expires_at))
    store._current(credential, cutoff)
    return selected, signature, cutoff


async def read_history_header(
    store: CodingPreparedStore,
    scope: CompanyControlScope,
    credential: AuthenticatedWorkerIdentity,
    action_id: UUID,
    *,
    end_us: int,
) -> CodingHeaderRead:
    """Owner/native/ACL history proof before header bytes, without current C/Goal/health."""
    end = store._end(credential, None, end_us)

    async def gate(
        header: CodingPreparedHeader | None = None,
    ) -> tuple[NativeCostSelection, str, int]:
        async with management_owner_transaction(
            store.factory, scope, credential.identity, allow_paused=True
        ) as (session, control, _):
            return await validate_history_locked(
                store, session, control, scope, credential, action_id, header=header, end_us=end
            )

    selected, signature, end = await store._owned(gate(), credential, end)
    # The selected value is an actual native query result, never a caller descriptor.
    from nexus.company.management.cycle_cost_contracts import NativeCostSelection

    assert isinstance(selected, NativeCostSelection)
    reference = prepared_reference(selected.action.proposal)
    header = decode_header(
        await store._owned(store._io._read(reference.header, end), credential, end), reference
    )
    final, final_signature, end = await store._owned(gate(header), credential, end)
    if final != selected or final_signature != signature:
        raise ManagementDeniedError("Coding history/source proof changed during metadata read")
    store._current(credential, end)
    return CodingHeaderRead(header, reference, signature, end)
