"""Current C/native/static review gates; private body I/O belongs outside this lock."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.action_review_resources import (
    action_resource_symbols,
    review_named_artifacts,
)
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.coding_intent import require_coding_registry
from nexus.company.management.coding_prepared_checks import require_action_header, shorten
from nexus.company.management.coding_prepared_contracts import (
    CodingPreparedRef,
    StoredCodingRequest,
    prepared_reference,
)
from nexus.company.management.control_support import db_clock
from nexus.company.management.owner_view_sources import owner_brain_scope
from nexus.company.management.plan_registration import registration
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.company.management.planning_prepared_contracts import PlanningModelParameters
from nexus.company.management.transactions import ManagementDeniedError
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.core.llm.company_pricing import quote_cost
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest, snapshot
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl
from nexus.harness.model_authorizer_contracts import model_action_parameters

if TYPE_CHECKING:
    from nexus.company.management.coding_prepared_store import CodingPreparedStore
    from nexus.execution.coding_services import CodingServices


@dataclass(frozen=True, slots=True)
class CodingReviewSelection:
    """Descriptive first native/static read; the reader separately seals actual issuance."""

    proposal_sha256: str
    binding_sha256: str
    registration_sha256: str
    run_id: UUID
    owner_id: UUID
    reference: CodingPreparedRef
    static_artifacts: tuple[ArtifactRevisionRef, ...]
    static_resources: tuple[UUID, ...]
    read_end_us: int

    def original_values(self) -> tuple[object, ...]:
        return (
            self.proposal_sha256,
            self.binding_sha256,
            self.registration_sha256,
            self.run_id,
            self.owner_id,
            self.reference,
            self.static_artifacts,
            self.static_resources,
        )


async def select_coding_review(
    services: CodingServices,
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    proposal: ActionProposal,
    work: ExecutionWork,
    binding: CurrentPlanBinding,
    *,
    end_us: int,
) -> CodingReviewSelection:
    """Actual C registration and all static READ precede any protected preparation byte.

    Cohesion exception: keep the complete C/owner/recipe/native tuple and first
    static cutoff adjacent; no DTO marker can skip a missing source permission.
    """
    from nexus.company.management.action_review_store import review_disclosure

    services.require_composition()
    require_time(end_us)
    if type(owner) is not AuthenticatedWorkerIdentity or not session.in_transaction():
        raise ManagementDeniedError("Coding review requires its actual authenticated owner/CC read")
    owner.require_time(await db_clock(session))
    admission = services.management.catalog.nexus_coding_admission
    assert admission is not None
    slot = admission.slots[1]
    parameters = PlanningModelParameters.model_validate_json(json.dumps(proposal.parameters))
    expected = registration(slot.child.binding, slot.work, slot.child.quota)
    if (
        (
            scope.company_id,
            scope.principal_id,
            owner.identity.principal_id,
            owner.identity.workspace_id,
        )
        != (
            admission.company_id,
            control.owner_id,
            control.owner_id,
            slot.child.binding.workspace_id,
        )
        or (work.workflow_name, work.workflow_version, work.model_profile)
        != ("company.coding.v1", "v1", "engineering")
        or snapshot(work).registration != expected
        or work.registration_hash != registration_digest(expected)
        or work.registration_hash != binding.work_sha256
        or binding.child != slot.child
        or binding.work != slot.work
        or binding.procedure_id != admission.procedure.procedure_id
        or (proposal.company_id, proposal.task_id, proposal.trace_id, proposal.actor_id)
        != (work.company_id, work.task_id, work.trace_id, work.actor_id)
        or (proposal.tool, proposal.tool_version, proposal.resource)
        != (slot.tool.tool, slot.tool.tool_version, slot.tool.resource)
        or (
            parameters.registry_id,
            parameters.registry_revision,
            parameters.price_version,
            parameters.input_recipe_id,
            parameters.input_recipe_revision,
        )
        != (
            services.registry_id,
            services.management.catalog.models.revision,
            services.management.catalog.models.pricebook_version,
            services.recipe.recipe_id,
            services.recipe.revision,
        )
        or proposal.price_version != parameters.price_version
    ):
        raise ManagementDeniedError(
            "Coding review differs from its exact current C/owner/native scope"
        )
    reference = prepared_reference(proposal)
    symbols = await action_resource_symbols(session, binding, proposal, services.management.catalog)
    artifacts, resources = await review_named_artifacts(
        session, binding, proposal, services.management.catalog, symbols
    )
    disclosure = await review_disclosure(
        session, control, scope, owner.identity, services.source_views, artifacts, resources
    )
    if disclosure is None:
        raise ManagementDeniedError("Coding static charter/target source READ is unavailable")
    before, now = clock_us(), await db_clock(session)
    windows = (owner.expires_at, *((disclosure.valid_until,) if disclosure.valid_until else ()))
    end_us = shorten(end_us, before, now, windows)
    services.require_composition()
    return CodingReviewSelection(
        action_hash(proposal),
        canonical_sha256(binding),
        work.registration_hash,
        work.run_id,
        control.owner_id,
        reference,
        artifacts,
        resources,
        end_us,
    )


async def validate_coding_review(
    services: CodingServices,
    session: AsyncSession,
    control: CompanyControl,
    scope: CompanyControlScope,
    owner: AuthenticatedWorkerIdentity,
    proposal: ActionProposal,
    work: ExecutionWork,
    binding: CurrentPlanBinding,
    selected: CodingReviewSelection,
    store: CodingPreparedStore,
    loaded: StoredCodingRequest,
    *,
    end_us: int,
) -> int:
    """Final same-CC current static/native/H owner proof, preserving the FIRST cutoff."""
    end_us = min(end_us, selected.read_end_us, loaded.read_end_us)
    current = await select_coding_review(
        services, session, control, scope, owner, proposal, work, binding, end_us=end_us
    )
    if current.original_values() != selected.original_values():
        raise ManagementDeniedError("Coding original native/static selection changed during read")
    store.require_loaded(loaded, owner, None, mode="owner", end_us=end_us)
    prepared = loaded.prepared
    model = require_coding_registry(prepared, services.management.catalog.models)
    quote = quote_cost(model.price, prepared.request.bounds, now=await db_clock(session))
    if (
        proposal.estimated_cost_usd != quote.amount_usd
        or loaded.reference != selected.reference
        or proposal.parameters != model_action_parameters(prepared.request, prepared.input_recipe)
        or services.estimator.estimate(
            prepared.request, services.management.catalog.models, services.recipe
        )
        != prepared.input_estimate
    ):
        raise ManagementDeniedError(
            "Coding complete input/model financial proof differs from native action"
        )
    require_action_header(proposal, loaded.header)
    end_us = min(
        end_us,
        current.read_end_us,
        await store.validate_loaded_locked(
            session,
            control,
            owner_brain_scope(scope, owner.identity),
            loaded,
            owner,
            None,
            mode="owner",
            now=await db_clock(session),
        ),
    )
    services.require_composition()
    require_time(end_us)
    return end_us
