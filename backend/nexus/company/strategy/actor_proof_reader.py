"""Actual selected E/EV Strategy READ, independent of the taskless owner reader."""

from uuid import uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.brain.base import BrainReadScope
from nexus.company.brain.scope_support import revalidate_brain_scope
from nexus.company.management.acceptance_errors import require_acceptance
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.cycle_admission import validate_stockflow_cycle
from nexus.company.management.cycle_catalog_checks import validate_cycle_catalog
from nexus.company.management.plan_models import ManagementPlanRevision
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.plans import PlanPayload
from nexus.company.management.report_input_contracts import native_author
from nexus.company.management.revision_store import plan_record, plan_reference
from nexus.company.management.strategy_transition_observation import validate_transition_proof
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.strategy.actor_proof_contracts import SelectedStrategyProof
from nexus.company.strategy.application_role import require_strategy_application_role
from nexus.company.strategy.current_proof_read import (
    assemble_strategy_current_proof,
    read_strategy_proof_material_locked,
)
from nexus.company.strategy.input_reader import StrategyInputReader
from nexus.company.strategy.publication_protection import require_credential
from nexus.execution.cycle_partition_checks import require_cycle_native_partition
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import db_now
from nexus.harness.journal_models import CompanyControl


class StrategyActorProofReader:
    """Server-configured reader; selection is derived from actual current approved full plan."""

    def __init__(self, reader: StrategyInputReader) -> None:
        require_acceptance(isinstance(reader, StrategyInputReader))
        self.reader = reader

    async def _current_actor(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        credential: AuthenticatedWorkerIdentity,
    ) -> tuple[CurrentPlanBinding, PlanPayload]:
        """Check actual actor/task READ, exact current plan and unchanged full native family."""
        require_acceptance(
            session.in_transaction()
            and not control.paused
            and control.company_id == work.company_id == self.reader.catalog.company_id
            and (identity.principal_id, identity.workspace_id) == (work.actor_id, work.workspace_id)
            and isinstance(credential, AuthenticatedWorkerIdentity)
            and credential.identity == identity
            and work.state not in {"blocked", "outcome_unknown"}
        )
        await require_strategy_application_role(session)
        require_credential(credential, identity, scope, await db_now(session))
        binding = await ManagementPlanStore.current_binding(session, work.company_id, work.task_id)
        require_acceptance(binding is not None)
        assert binding is not None
        row = await session.get(
            ManagementPlanRevision, (work.company_id, binding.plan.plan_revision_id)
        )
        require_acceptance(row is not None)
        assert row is not None
        record = plan_record(row)
        payload = record.payload
        admission = validate_cycle_catalog(self.reader.catalog.cycle_admission, self.reader.catalog)
        require_acceptance(admission is not None)
        assert admission is not None
        matched = validate_stockflow_cycle(admission, self.reader.catalog.models, payload)
        require_acceptance(
            matched is not None
            and matched.stage == "full"
            and payload.plan.revision == 2
            and payload.strategy_selection is not None
            and plan_reference(record) == binding.plan
        )
        actual, saved = native_author(work)
        slots = tuple(slot for slot in admission.slots[2:4] if slot.child.binding == actual)
        require_acceptance(len(slots) == 1)
        slot = slots[0]
        require_acceptance(
            binding.child == slot.child
            and binding.work == slot.work
            and binding.work_sha256 == work.registration_hash
            and saved.quota == slot.child.quota
            and work.model_requests_limit
            == work.model_requests_used
            == work.model_requests_delegated
            == 0
        )
        await require_cycle_native_partition(
            session,
            control,
            work,
            identity,
            admission=admission,
            registry=self.reader.catalog.models,
        )
        await revalidate_brain_scope(session, control, scope, identity)
        return binding, payload

    async def load_selected_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        work: ExecutionWork,
        identity: VerifiedIdentity,
        *,
        credential: AuthenticatedWorkerIdentity,
    ) -> SelectedStrategyProof:
        """Read twice as E/EV, then finish with current actor and the last DB clock."""
        require_acceptance(isinstance(work, ExecutionWork))
        require_acceptance(type(work.fence) is int and work.fence >= 0)
        fence, catalog_sha = work.fence, canonical_sha256(self.reader.catalog)
        scope = BrainReadScope(
            company_id=work.company_id,
            workspace_id=work.workspace_id,
            principal_id=identity.principal_id,
            operation_id=uuid5(work.run_id, "strategy-actor-proof:v1"),
            trace_id=work.trace_id,
            task_id=work.task_id,
            task_trace_id=work.trace_id,
            actor_id=work.actor_id,
        )
        binding, payload = await self._current_actor(
            session, control, work, scope, identity, credential
        )
        require_acceptance(work.fence == fence)
        selection = payload.strategy_selection
        assert selection is not None
        first = await read_strategy_proof_material_locked(
            self.reader, session, control, scope, identity, selection, credential
        )
        current = await read_strategy_proof_material_locked(
            self.reader, session, control, scope, identity, selection, credential
        )
        assembled_at = await db_now(session)
        require_acceptance(first.observed_at <= current.observed_at <= assembled_at)
        proof = assemble_strategy_current_proof(
            selection, first, current, credential, scope, identity, assembled_at
        )
        require_acceptance(
            proof.initial.sources.credential == credential
            and proof.current.sources.credential == credential
            and proof.original.prepared.original.policy == self.reader.production_policy
        )
        candidate = validate_transition_proof(payload, self.reader.catalog, proof)
        final_binding, final_payload = await self._current_actor(
            session, control, work, scope, identity, credential
        )
        require_acceptance(
            binding == final_binding
            and payload == final_payload
            and work.fence == fence
            and canonical_sha256(self.reader.catalog) == catalog_sha
        )
        now = await db_now(session)
        result = SelectedStrategyProof(binding, proof, candidate, first.observed_at)
        result.require_time(now)
        require_credential(credential, identity, scope, now)
        return result
