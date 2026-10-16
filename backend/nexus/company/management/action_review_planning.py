"""Concrete protected planning disclosure joins; no marker is a permission or Brain alias."""

import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.control_support import db_clock
from nexus.company.management.owner_view_sources import OwnerViewSources, owner_brain_scope
from nexus.company.management.plan_support import CurrentPlanBinding, PlanAdmissionCatalog
from nexus.company.management.planning_intent import require_planning_registry
from nexus.company.management.planning_native_facts import clock_us, require_time
from nexus.company.management.planning_prepared_checks import (
    native_prepared,
    require_native_header,
    source_read,
)
from nexus.company.management.planning_prepared_contracts import (
    PlanningModelParameters,
    StoredPlanningRequest,
    descriptor_for,
    descriptor_reference,
    encode_prepared,
    prepared_reference,
)
from nexus.company.management.planning_prepared_store import PlanningPreparedStore
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.runtime_models import ExecutionWork
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl
from nexus.harness.model_authorizer_contracts import model_action_parameters


@dataclass(frozen=True, slots=True)
class PlanningReviewSelection:
    """Immutable first metadata read, never a caller-issued authorization witness."""

    proposal_sha256: str
    binding_sha256: str
    registration_sha256: str
    run_id: UUID
    owner_id: UUID


class PlanningReviewInputs:
    """Same original native/storage/catalog dependencies across every awaited read."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        catalog: PlanAdmissionCatalog,
        sources: OwnerViewSources,
        store: PlanningPreparedStore,
    ) -> None:
        if (
            type(store) is not PlanningPreparedStore
            or store.factory is not factory
            or store.sources.artifacts is not sources.artifacts
            or store.sources.freshness is not sources.freshness
        ):
            raise ValueError("Planning review needs its concrete same-factory/source store")
        self.factory, self.catalog, self.sources, self.store = factory, catalog, sources, store
        self._original = self._pins()

    def _pins(self) -> tuple[object, ...]:
        return (
            self.factory,
            self.catalog,
            self.sources,
            self.store,
            self.store.factory,
            self.sources.artifacts,
            self.sources.freshness,
            canonical_sha256(self.catalog),
        )

    def require_composition(self) -> None:
        """The optional read service cannot substitute a catalog, factory or source adapter."""
        actual = self._pins()
        if (
            any(a is not b for a, b in zip(actual[:7], self._original[:7], strict=True))
            or actual[7:] != self._original[7:]
            or self.store.factory is not self.factory
            or self.store.sources.artifacts is not self.sources.artifacts
            or self.store.sources.freshness is not self.sources.freshness
        ):
            raise ManagementDeniedError("Original planning review composition changed")
        self.store._composition()

    def select(
        self,
        control: CompanyControl,
        proposal: ActionProposal,
        work: ExecutionWork,
        binding: CurrentPlanBinding,
    ) -> PlanningReviewSelection:
        """Select the real fixed planner action, not a prefix-shaped or posted marker."""
        self.require_composition()
        parameters = PlanningModelParameters.model_validate_json(json.dumps(proposal.parameters))
        prepared_reference(proposal)
        if (
            (work.workflow_name, work.workflow_version) != ("company.planning.v1", "v1")
            or (proposal.tool, proposal.tool_version, proposal.resource)
            != ("model.request.v1", "v1", f"model:{parameters.registry_id}")
            or (proposal.company_id, proposal.task_id, proposal.trace_id, proposal.actor_id)
            != (work.company_id, work.task_id, work.trace_id, work.actor_id)
            or work.registration_hash != binding.work_sha256
            or (
                self.catalog.company_id,
                self.catalog.models.revision,
                self.catalog.models.pricebook_version,
            )
            != (proposal.company_id, parameters.registry_revision, parameters.price_version)
            or not any(
                row.registry_id == parameters.registry_id for row in self.catalog.models.models
            )
        ):
            raise ManagementDeniedError("Planning review differs from its exact native/catalog ABI")
        return PlanningReviewSelection(
            action_hash(proposal),
            canonical_sha256(binding),
            work.registration_hash,
            work.run_id,
            control.owner_id,
        )

    async def load(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        action_id: UUID,
        *,
        end_us: int,
    ) -> StoredPlanningRequest:
        """Call only after the outer CompanyControl transaction has closed."""
        self.require_composition()
        result = await self.store.load_owner(scope, identity, action_id, end_us=end_us)
        self.require_composition()
        require_time(min(end_us, result.read_end_us))
        return result

    async def validate(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        proposal: ActionProposal,
        work: ExecutionWork,
        binding: CurrentPlanBinding,
        selected: PlanningReviewSelection,
        loaded: StoredPlanningRequest,
        *,
        end_us: int,
    ) -> int:
        """Rebind exact descriptor, complete conditions and current source closure under CC.

        Cohesion exception: reconstruction, immutable joins and the final source clock
        share one sequence so no partial marker check can authorize disclosure.
        """
        end_us = min(end_us, loaded.read_end_us)
        require_time(end_us)
        if (
            not session.in_transaction()
            or self.select(control, proposal, work, binding) != selected
        ):
            raise ManagementDeniedError("Planning native/owner binding changed during read")
        prepared = loaded.prepared
        require_planning_registry(prepared, self.catalog.models)
        _, body = encode_prepared(prepared)
        header = descriptor_for(
            prepared,
            body,
            run_id=work.run_id,
            registration_sha256=work.registration_hash,
            owner_id=control.owner_id,
        )
        reference, _ = descriptor_reference(header)
        call = prepared.request
        if (
            reference != loaded.reference
            or reference != prepared_reference(proposal)
            or proposal.parameters != model_action_parameters(call, prepared.input_recipe)
            or (call.company_id, call.action_id, call.task_id, call.trace_id, call.actor_id)
            != (proposal.company_id, proposal.action_id, work.task_id, work.trace_id, work.actor_id)
        ):
            raise ManagementDeniedError("Planning request, descriptor or native hash changed")
        expected = (
            tuple(
                ResourceRevision(
                    resource=f"brain.resource:{row.resource_id}", revision=f"acl:{row.generation}"
                )
                for row in header.contributors
            )
            + tuple(
                ResourceRevision(
                    resource=f"brain.source:{row.source_id}",
                    revision=f"head:{row.generation}:{row.current.source_revision_id}",
                )
                for row in header.source_heads
            )
            + (reference.condition,)
        )
        if proposal.preconditions != expected:
            raise ManagementDeniedError(
                "Planning action conditions differ from complete input closure"
            )
        native = await native_prepared(
            session,
            control,
            owner_brain_scope(scope, identity),
            identity,
            work.task_id,
            proposal.action_id,
            self.store.recipe,
            lease=None,
        )
        await require_native_header(session, native, header, self.store.recipe)
        if native.current != binding or native.proposal != proposal:
            raise ManagementDeniedError("Final planning native target or proposal changed")
        windows = await source_read(
            session, control, owner_brain_scope(scope, identity), identity, header, self.sources
        )
        before = clock_us()
        now = await db_clock(session)
        end_us = min(
            (end_us, *(before + (end - now) // timedelta(microseconds=1) for end in windows))
        )
        self.require_composition()
        require_time(end_us)
        return end_us
