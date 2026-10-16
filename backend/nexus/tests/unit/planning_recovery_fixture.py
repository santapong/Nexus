"""Concrete recovery graph with synthetic signed sessions and supplied native/source delivery.

Cohesion exception: the one fixture keeps the actual estimator/context/protected/native
composition together; it neither registers Work nor qualifies SQL/source access.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.builder.contained_query import clock_us
from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.management.action_review_planning import PlanningReviewInputs
from nexus.company.management.owner_view_sources import SourceDisclosure
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.core.llm.company_pricing import quote_cost
from nexus.core.llm.company_routing import RoutedModel
from nexus.execution.planning_context import PlanningState
from nexus.execution.planning_preparation_recovery import PreparedWaitRecovery
from nexus.execution.runtime_support import snapshot
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl
from nexus.tests.unit.nexus_intent_fixture import Boundary
from nexus.tests.unit.nexus_report_fixture import credentials


@dataclass(frozen=True, slots=True)
class RecoveryCase:
    value: Boundary
    check: PreparedWaitRecovery
    current: CurrentPlanBinding


async def recovery_case(tmp_path: Path) -> RecoveryCase:
    """Real concrete graph and genuine synthetic JWTs; native/source delivery stays supplied."""
    from uuid import uuid5

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nexus.company.brain.artifact_store import BoundedArtifactReader
    from nexus.company.brain.blob_store import ProtectedBlobStore
    from nexus.company.brain.context import ContextLimits, ContextSelection
    from nexus.company.brain.context_store import PersistentContextAssembler
    from nexus.company.brain.retrieval import RetrievalLimits
    from nexus.company.brain.retrieval_store import PersistentBrainRetriever
    from nexus.company.contracts.actions import ActionProposal, ApprovalDecision
    from nexus.company.management.action_review_planning import PlanningReviewInputs
    from nexus.company.management.lifecycle import PlanRevisionRef
    from nexus.company.management.nexus_planning_intent import NexusPlanningIntentCheck
    from nexus.company.management.owner_view_sources import OwnerViewSources
    from nexus.company.management.plan_support import CurrentPlanBinding, PlanSourceFreshness
    from nexus.company.management.planning_authority import (
        ManagementPlanningAuthority,
        PlanningRolePolicy,
    )
    from nexus.company.management.planning_prepared_contracts import (
        StoredPlanningRequest,
        descriptor_for,
        descriptor_reference,
        encode_prepared,
    )
    from nexus.company.management.planning_prepared_store import PlanningPreparedStore
    from nexus.execution.effect_store import EffectStore
    from nexus.execution.management_services import ManagementExecutionServices
    from nexus.execution.planning_preparation_recovery import PreparedWaitRecovery
    from nexus.execution.planning_services import PlanningOperation, PlanningServices
    from nexus.execution.runtime_approval_recovery import recovery_scope
    from nexus.execution.runtime_support import snapshot
    from nexus.harness.canonical import action_hash
    from nexus.harness.journal_submission import pending_action_record
    from nexus.harness.model_evidence import FileModelEvidenceStore
    from nexus.harness.model_input_estimator import FullContextInputEstimator
    from nexus.tests.unit.nexus_intent_fixture import boundary
    from nexus.tests.unit.nexus_planning_fixture import planning_check
    from nexus.tests.unit.test_planning_services import services as old_services

    value = boundary(0)
    factory = async_sessionmaker[AsyncSession]()
    composite = await planning_check(value, EffectStore(factory), tmp_path)
    guard = cast(NexusPlanningIntentCheck, composite._checks[0])
    prepared = guard._prepared
    blobs = ProtectedBlobStore(tmp_path / "blobs", storage_symbol="fixture.recovery")
    artifacts = BoundedArtifactReader(factory, blobs)
    freshness = cast(PlanSourceFreshness, AsyncMock())
    management = ManagementExecutionServices(value.catalog, artifacts, freshness)
    authority = ManagementPlanningAuthority(
        management,
        PlanningRolePolicy(
            company_id=value.work.company_id,
            workflow_name="company.planning.v1",
            workflow_version="v1",
            model_profile="reasoning",
            data_classification="internal",
            role_system_text="Synthetic finite role",
        ),
        prepared.input_recipe,
    )
    contexts = PersistentContextAssembler(
        factory,
        PersistentBrainRetriever(factory, blobs, limits=RetrievalLimits()),
        authority,
        limits=ContextLimits(policy_version="synthetic-context"),
    )
    store = PlanningPreparedStore(
        factory, blobs, OwnerViewSources(artifacts, freshness), prepared.input_recipe
    )
    admission = value.catalog.nexus_cycle_admission
    assert admission is not None
    bound = admission.slots[0].child.binding
    actor = await credentials(bound).current(bound)
    owner = await credentials(admission.procedure.binding).current(admission.procedure.binding)
    legacy = old_services(tmp_path / "unused")
    configured = PlanningServices(
        factory,
        management,
        contexts,
        store,
        FullContextInputEstimator(value.catalog.models, prepared.input_recipe),
        prepared.input_recipe,
        credentials(bound),
        legacy.resolver,
        FileModelEvidenceStore(tmp_path / "evidence"),
        UUID(int=333),
        prepared.request.registry_id,
        512,
        ContextSelection(company_id=value.work.company_id),
    )
    operation = PlanningOperation(configured, "recovery-unit", clock_us() + 30_000_000)
    operation.credential = actor
    value.work.segment_id = uuid5(value.work.run_id, "nexus-execution-segment-v1:1")
    value.work.lease_until = datetime.now(UTC).replace(year=2025)
    _, body = encode_prepared(prepared)
    reference, _ = descriptor_reference(
        descriptor_for(
            prepared,
            body,
            run_id=value.work.run_id,
            registration_sha256=value.work.registration_hash,
            owner_id=value.control.owner_id,
        )
    )
    proposal = ActionProposal.model_validate_json(value.action.proposal_json).model_copy(
        update={"preconditions": (reference.condition,)}
    )
    value.action.proposal_json, value.action.proposal_hash = (
        proposal.model_dump_json(),
        action_hash(proposal),
    )
    assert value.action.approval_json is not None
    decision = ApprovalDecision.model_validate_json(value.action.approval_json).model_copy(
        update={"action_hash": value.action.proposal_hash}
    )
    value.action.approval_json = decision.model_dump_json()
    value.action.state, value.action.consumed_at = "awaiting_approval", None
    action = pending_action_record(value.action)
    assert prepared.binding.expected_plan_revision_id is not None
    current = CurrentPlanBinding(
        company_id=bound.company_id,
        plan=PlanRevisionRef(
            company_id=bound.company_id,
            plan_id=admission.plan_id,
            plan_revision_id=prepared.binding.expected_plan_revision_id,
            revision=1,
            sha256="a" * 64,
        ),
        child=admission.slots[0].child,
        work=admission.slots[0].work,
        work_sha256=value.work.registration_hash,
        procedure_id=admission.procedure.procedure_id,
    )
    owner_scope = CompanyControlScope(
        company_id=bound.company_id,
        principal_id=owner.identity.principal_id,
        operation_id=UUID(int=1000),
        trace_id=UUID(int=1001),
    )
    inputs = PlanningReviewInputs(factory, value.catalog, store.sources, store)
    selected = inputs.select(value.control, action.proposal, value.work, current)
    check = PreparedWaitRecovery(
        operation,
        owner_scope,
        owner,
        actor,
        recovery_scope(bound, value.action.id),
        snapshot(value.work),
        action,
        selected,
        StoredPlanningRequest(prepared, reference, operation.end),
        admission.goal,
        current.plan.plan_revision_id,
        inputs,
    )
    return RecoveryCase(value, check, current)


@dataclass
class RecoveryDelivery:
    """Supplied native/source delivery only; an emulated rollback is not SQL evidence."""

    fake: MagicMock
    active: int = 0
    commits: int = 0
    rollbacks: int = 0
    disclosures: int = 0
    load_delay: float = 0
    load_gate: asyncio.Event | None = None
    load_started: asyncio.Event | None = None
    first_static_until: datetime | None = None
    after_load: Callable[[], None] | None = None


def install_recovery_delivery(
    case: RecoveryCase, monkeypatch: pytest.MonkeyPatch
) -> RecoveryDelivery:
    """Exercise the real driver/check/writer while supplying SQL, prepared read and source facts."""
    from nexus.execution import planning_preparation_recovery as driver
    from nexus.execution import runtime_approval_recovery as native
    from nexus.execution import runtime_store

    value, check = case.value, case.check
    check.operation.finish()
    fake = MagicMock(spec=AsyncSession)
    fake.in_transaction.return_value = True
    result = MagicMock()
    result.all.return_value = [value.action]
    fake.scalars = AsyncMock(return_value=result)
    fake.scalar = AsyncMock(return_value=None)
    fake.flush = AsyncMock()
    delivery = RecoveryDelivery(fake=fake, load_started=asyncio.Event())
    session = cast(AsyncSession, fake)

    @asynccontextmanager
    async def transaction(
        factory: object, scope: LedgerScope, identity: VerifiedIdentity
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, object]]:
        assert factory is check.services.factory
        assert scope.principal_id == identity.principal_id == value.work.actor_id
        assert not delivery.active
        fields = (
            "state",
            "waiting_action_id",
            "fence",
            "worker_id",
            "lease_until",
            "lease_mode",
            "lease_principal_id",
            "segment_number",
            "segment_id",
        )
        saved = {key: getattr(value.work, key) for key in fields}
        delivery.active += 1
        try:
            yield session, value.control, object()
        except BaseException:
            delivery.rollbacks += 1
            for key, item in saved.items():
                setattr(value.work, key, item)
            raise
        else:
            delivery.commits += 1
        finally:
            delivery.active -= 1

    async def state(*args: object, **kwargs: object) -> PlanningState:
        return PlanningState(
            snapshot(value.work),
            check.expected_goal,
            case.current.plan.plan_id,
            check.expected_head,
            value.control.policy_version,
            value.now,
            clock_us(),
        )

    async def disclosure(*args: object, **kwargs: object) -> SourceDisclosure:
        delivery.disclosures += 1
        return SourceDisclosure(delivery.first_static_until if delivery.disclosures <= 2 else None)

    async def validate(self: PlanningReviewInputs, *args: object, end_us: int) -> int:
        assert self.store is check.services.prepared
        return min(end_us, check.loaded.read_end_us)

    async def load(*args: object, **kwargs: object) -> object:
        assert not delivery.active, "Protected read cannot hold the outer company transaction"
        assert delivery.load_started is not None
        delivery.load_started.set()
        if delivery.load_gate is not None:
            await delivery.load_gate.wait()
        if delivery.load_delay:
            await asyncio.sleep(delivery.load_delay)
        if delivery.after_load is not None:
            delivery.after_load()
        return check.loaded

    price = value.catalog.models.models[0].price
    assert price is not None
    selected = RoutedModel(
        model=value.catalog.models.models[0],
        quote=quote_cost(price, check.loaded.prepared.request.bounds, now=value.now),
    )
    monkeypatch.setattr(driver, "runtime_transaction", transaction)
    monkeypatch.setattr(runtime_store, "runtime_transaction", transaction)
    monkeypatch.setattr(driver, "state_locked", state)
    monkeypatch.setattr(
        ManagementPlanStore, "current_binding", AsyncMock(return_value=case.current)
    )
    monkeypatch.setattr(driver, "execution_row", AsyncMock(return_value=value.work))
    monkeypatch.setattr(runtime_store, "execution_row", AsyncMock(return_value=value.work))
    monkeypatch.setattr(driver, "db_now", AsyncMock(return_value=value.now))
    monkeypatch.setattr(native, "db_now", AsyncMock(return_value=value.now))
    monkeypatch.setattr(driver, "require_brain_scope", AsyncMock())
    monkeypatch.setattr(driver, "action_resource_symbols", AsyncMock(return_value=("fixture",)))
    monkeypatch.setattr(driver, "review_named_artifacts", AsyncMock(return_value=((), ())))
    monkeypatch.setattr(driver, "review_disclosure", disclosure)
    monkeypatch.setattr(PlanningReviewInputs, "validate", validate)
    monkeypatch.setattr(check.services.contexts, "revalidate_context", AsyncMock(return_value=()))
    monkeypatch.setattr(driver, "quote_locked", AsyncMock(return_value=selected))
    monkeypatch.setattr(check.services.prepared, "load_actor", load)
    return delivery
