"""Supplied SQL/identity delivery and concrete storage; no actual PostgreSQL authority proof.

Cohesion exception: the shared native/header/real-file setup and focused source/
cutoff/ownership controls exceed400 lines, without a second fixture module.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contained_query import clock_us
from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.management import cycle_model_reader as module
from nexus.company.management.cycle_model_reader import CycleModelReader
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.harness.model_evidence import FileModelEvidenceStore, ModelEvidence
from nexus.tests.unit.nexus_cycle_fixture import case
from nexus.tests.unit.test_nexus_coding_catalog import coding_case


def reader(root: Path) -> CycleModelReader:
    _, catalog = coding_case()
    return CycleModelReader(async_sessionmaker(), catalog, FileModelEvidenceStore(root))


@pytest.mark.parametrize("hour, day", [(16, 16), (17, 17)])
def test_intent_fixture_retains_actual_bangkok_billing_boundary(
    monkeypatch: pytest.MonkeyPatch, hour: int, day: int
) -> None:
    from datetime import UTC, date, datetime

    from nexus.harness.journal_budget import billing_day
    from nexus.tests.unit import selected_intent_boundary_fixture as fixture

    instant = datetime(2026, 10, 16, hour, tzinfo=UTC)
    monkeypatch.setattr(fixture, "datetime", SimpleNamespace(now=lambda _: instant))
    value = fixture.intent_boundary()
    assert value.now == instant
    assert value.hold.day == billing_day(instant) == date(2026, 10, day)
    with pytest.raises(ValueError, match="timezone-aware"):
        billing_day(instant.replace(tzinfo=None))


def test_old_six_role_catalog_cannot_be_labelled_whole_full_company(tmp_path: Path) -> None:
    _, catalog = case()
    with pytest.raises(ValueError):
        CycleModelReader(async_sessionmaker(), catalog, FileModelEvidenceStore(tmp_path))


async def test_non_witness_or_foreign_identity_denies_before_private_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = reader(tmp_path)
    private = AsyncMock(side_effect=AssertionError("private read before current owner"))
    monkeypatch.setattr(value.evidence, "load", private)
    scope = CompanyControlScope(
        company_id=value.catalog.company_id,
        principal_id=UUID(int=900),
        operation_id=UUID(int=901),
        trace_id=UUID(int=902),
    )
    with pytest.raises(ValueError):
        await value.read(
            scope,
            cast(
                AuthenticatedWorkerIdentity,
                VerifiedIdentity(
                    principal_id=scope.principal_id,
                    workspace_id=value.admission.procedure.binding.workspace_id,
                ),
            ),
            UUID(int=903),
            end_us=clock_us() + 30_000_000,
        )  # Deliberately wrong runtime type, supplied test data.
    private.assert_not_awaited()


def test_same_path_fresh_store_cannot_replace_original_storage_identity(tmp_path: Path) -> None:
    value = reader(tmp_path)
    value.evidence = FileModelEvidenceStore(tmp_path)
    with pytest.raises(ValueError):
        value.require_composition()


async def supplied_case(root: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Actual files/concrete graph; native/current-source service results are supplied.

    This exercises original cutoff/ordering/ownership, not SQL/RLS qualification.
    """
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from uuid import uuid5

    from nexus.company.brain.access_contracts import ResourceGeneration
    from nexus.company.brain.artifact_store import BoundedArtifactReader
    from nexus.company.brain.blob_store import ProtectedBlobStore
    from nexus.company.brain.source_models import BrainSourceRevision
    from nexus.company.brain.source_registry import SourcePolicy
    from nexus.company.brain.sources import ArtifactRevisionRef, SourceHead, SourceRevisionRef
    from nexus.company.contracts.actions import ActionProposal, ApprovalDecision, ResourceRevision
    from nexus.company.contracts.results import ActionReceipt
    from nexus.company.management.acceptance_freshness import (
        QualifiedFreshness,
        RegisteredSourceFreshness,
    )
    from nexus.company.management.canonical import canonical_sha256
    from nexus.company.management.cycle_cost_contracts import (
        DirectoryCostWork,
        NativeCostAttempt,
        NativeCostHold,
        NativeCostSelection,
    )
    from nexus.company.management.owner_view_sources import OwnerViewSources
    from nexus.company.management.plan_models import ManagementOwnerDecision, ManagementPlanRevision
    from nexus.company.management.plan_registration import registration
    from nexus.company.management.planning_prepared_contracts import (
        BODY_REVISION,
        PlanningModelParameters,
        PlanningPreparedDescriptor,
        descriptor_reference,
    )
    from nexus.company.management.planning_prepared_store import PlanningPreparedStore
    from nexus.core.llm.company_adapter_contracts import request_hash
    from nexus.core.llm.company_pricing import quote_cost, reconcile_cost
    from nexus.execution.planning_application_config import PlanningSourcePolicies
    from nexus.execution.runtime_contracts import EffectRecord, ExecutionSnapshot
    from nexus.execution.runtime_support import registration_digest
    from nexus.harness.canonical import action_hash
    from nexus.harness.journal_budget import billing_day
    from nexus.harness.journal_contracts import ActionRecord
    from nexus.harness.journal_models import CompanyControl
    from nexus.harness.lifecycle import ActionState
    from nexus.harness.limits import LoopCounters
    from nexus.harness.model_authorizer_contracts import model_action_parameters
    from nexus.tests.unit.nexus_report_fixture import credentials
    from nexus.tests.unit.test_company_model_evidence import envelope

    profile, catalog = coding_case()
    slot = profile.slots[0]
    owner = await credentials(profile.procedure.binding).current(profile.procedure.binding)
    scope = CompanyControlScope(
        company_id=profile.company_id,
        principal_id=owner.identity.principal_id,
        operation_id=UUID(int=910),
        trace_id=UUID(int=911),
    )
    factory = async_sessionmaker()
    original = envelope()
    recipe = original.recipe.model_copy(update={"profile": "reasoning"})
    call = original.request.model_copy(
        update={
            "company_id": profile.company_id,
            "task_id": slot.work.task_id,
            "trace_id": slot.work.trace_id,
            "actor_id": slot.child.binding.actor_id,
            "attempt_id": original.request.action_id,
            "registry_id": catalog.models.models[0].registry_id,
            "registry_revision": catalog.models.revision,
            "price_version": catalog.models.pricebook_version,
        }
    )
    digest = request_hash(call)
    estimate = original.input_estimate.model_copy(
        update={
            "request_hash": digest,
            "registry_id": call.registry_id,
            "registry_revision": call.registry_revision,
            "recipe_id": recipe.recipe_id,
            "recipe_revision": recipe.revision,
        }
    )
    model = catalog.models.models[0]
    now = datetime.now(UTC)
    grant = ResourceGeneration(
        company_id=profile.company_id, resource_id=UUID(int=912), generation=1, expires_at=None
    )
    source_ref = SourceRevisionRef(
        company_id=profile.company_id,
        source_id=UUID(int=913),
        source_revision_id=UUID(int=914),
        revision="historical-revision",
    )
    head = SourceHead(
        company_id=profile.company_id,
        source_id=source_ref.source_id,
        current=source_ref,
        generation=1,
        observed_at=now,
        fresh_until=None,
        availability="available",
    )
    body_id = uuid5(call.action_id, BODY_REVISION)
    body = ArtifactRevisionRef(
        company_id=profile.company_id,
        artifact_id=body_id,
        artifact_revision_id=uuid5(body_id, digest),
        revision=BODY_REVISION,
        sha256="b" * 64,
        byte_length=1,
    )
    registered = registration(slot.child.binding, slot.work, slot.child.quota)
    header = PlanningPreparedDescriptor(
        company_id=profile.company_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        actor_id=call.actor_id,
        workspace_id=slot.child.binding.workspace_id,
        action_id=call.action_id,
        run_id=registered.run_id,
        owner_id=owner.identity.principal_id,
        registration_sha256=registration_digest(registered),
        request_sha256=digest,
        input_recipe_sha256=canonical_sha256(recipe),
        parameters=PlanningModelParameters.model_validate_json(
            json.dumps(model_action_parameters(call, recipe))
        ),
        goal=profile.goal,
        plan_id=profile.plan_id,
        expected_plan_revision_id=UUID(int=915),
        context_manifest_sha256="c" * 64,
        body=body,
        contributors=(grant,),
        source_heads=(head,),
    )
    reference, raw = descriptor_reference(header)
    conditions = (
        ResourceRevision(resource=f"brain.resource:{grant.resource_id}", revision="acl:1"),
        ResourceRevision(
            resource=f"brain.source:{source_ref.source_id}",
            revision=f"head:1:{source_ref.source_revision_id}",
        ),
        reference.condition,
    )
    reservation = quote_cost(model.price, call.bounds, now=now).amount_usd
    proposal = ActionProposal(
        company_id=profile.company_id,
        action_id=call.action_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        actor_id=call.actor_id,
        revision=1,
        tool="model.request.v1",
        tool_version="v1",
        resource="model:" + call.registry_id,
        parameters=model_action_parameters(call, recipe),
        preconditions=conditions,
        policy_version="historical-policy",
        price_version=call.price_version,
        estimated_cost_usd=reservation,
    )
    action = ActionRecord(
        company_id=profile.company_id,
        proposal=proposal,
        proposal_hash=action_hash(proposal),
        approval=ApprovalDecision(
            company_id=profile.company_id,
            decision_id=UUID(int=916),
            action_id=call.action_id,
            action_revision=1,
            action_hash=action_hash(proposal),
            approver_id=owner.identity.principal_id,
            decision="approved",
            issued_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=1),
        ),
        state=ActionState.AUTHORIZED,
        consumed_at=now - timedelta(microseconds=2),
    )
    zero = LoopCounters(model_requests=0, tool_attempts=0, rework_rounds=0, plan_revisions=0)
    work = ExecutionSnapshot(
        company_id=profile.company_id,
        registration=registered,
        workspace_id=slot.child.binding.workspace_id,
        actor_id=call.actor_id,
        parent_task_id=profile.procedure.binding.task_id,
        state="verifying",
        counters=zero.model_copy(update={"model_requests": 1}),
        delegated=zero,
        fence=2,
        worker_id=None,
        lease_principal_id=None,
        expires_at=None,
        segment_number=3,
        segment_id=UUID(int=917),
        waiting_action_id=None,
    )
    saved = original.model_copy(
        update={
            "request": call,
            "request_hash": digest,
            "action_hash": action.proposal_hash,
            "model": model,
            "registry_revision": call.registry_revision,
            "price_version": call.price_version,
            "recipe": recipe,
            "input_estimate": estimate,
            "source_event_at": now,
            "checked_at": now + timedelta(microseconds=1),
            "owner_id": owner.identity.principal_id,
            "result": original.result.model_copy(update={"request_id": call.request_id}),
        }
    )
    store = FileModelEvidenceStore(root / "model")
    artifact = await store.save(saved)
    receipt = ActionReceipt(
        company_id=profile.company_id,
        receipt_id=uuid5(call.action_id, "model-receipt-v1"),
        action_id=call.action_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        proposal_hash=action.proposal_hash,
        outcome="succeeded",
        recorded_at=saved.checked_at,
        artifacts=(artifact,),
    )
    intent = EffectRecord(
        company_id=profile.company_id,
        action_id=call.action_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        run_id=registered.run_id,
        proposal_hash=action.proposal_hash,
        intent_fence=1,
        attempt_kind="model_requests",
        state="succeeded",
        created_at=now - timedelta(microseconds=1),
        receipt=receipt,
        verification=None,
    )
    assert saved.result.usage
    selected = NativeCostSelection(
        directory=DirectoryCostWork(
            company_id=profile.company_id,
            task_id=call.task_id,
            trace_id=call.trace_id,
            actor_id=call.actor_id,
            workspace_id=work.workspace_id,
            parent_task_id=work.parent_task_id,
            root_task_id=profile.procedure.binding.task_id,
            allocation_usd=slot.child.allocation_usd,
            delegated_usd=Decimal(0),
            active=False,
            work=work,
        ),
        action=action,
        hold=NativeCostHold(
            company_id=profile.company_id,
            task_id=call.task_id,
            action_id=call.action_id,
            day=billing_day(intent.created_at),
            amount_usd=reservation,
            actual_usd=reconcile_cost(model.price, saved.result.usage, now=now).amount_usd,
            state="reconciled",
        ),
        intent=intent,
        attempt=NativeCostAttempt(
            company_id=profile.company_id,
            task_id=call.task_id,
            trace_id=call.trace_id,
            attempt_id=call.attempt_id,
            kind="model_requests",
            fence=1,
            reserved_at=intent.created_at,
        ),
    )
    policy = SourcePolicy(
        source_symbol="audit-source",
        authority_profile="audit-docs",
        data_classification="internal",
        media_type="text/plain",
        parser_version="v1",
        chunker_version="v1",
        search_config="simple",
        freshness_seconds=None,
        allowed_external_keys=frozenset({"doc"}),
    )
    sources = OwnerViewSources(
        BoundedArtifactReader(factory, ProtectedBlobStore(root / "brain", storage_symbol="brain")),
        RegisteredSourceFreshness(factory, PlanningSourcePolicies(policies=(policy,))),
    )
    prepared = PlanningPreparedStore(
        factory, ProtectedBlobStore(root / "prepared", storage_symbol="prepared"), sources, recipe
    )
    await prepared.blobs.save(reference.descriptor, raw)
    value = CycleModelReader(factory, catalog, store, prepared)
    control = CompanyControl(company_id=profile.company_id, owner_id=owner.identity.principal_id)
    session = MagicMock(spec=AsyncSession)
    revision = profile.payload("planning")
    row = ManagementPlanRevision(
        company_id=profile.company_id,
        plan_id=profile.plan_id,
        plan_revision_id=UUID(int=915),
        revision=1,
        goal_id=profile.goal.goal_id,
        goal_revision_id=profile.goal.revision_id,
        mandate_revision_id=profile.mandate.revision_id,
        sha256=canonical_sha256(revision),
        snapshot_json=revision.model_dump_json(),
        proposed_by=owner.identity.principal_id,
        recorded_at=now,
    )

    def scalar_result(query: Select[tuple[object]]) -> SimpleNamespace:
        entity = query.column_descriptions[0]["entity"]
        return SimpleNamespace(
            all=lambda: [row] if entity is ManagementPlanRevision else [ManagementOwnerDecision()]
        )

    session.scalars = AsyncMock(side_effect=scalar_result)
    source_row = BrainSourceRevision(
        company_id=profile.company_id,
        source_id=source_ref.source_id,
        source_revision_id=source_ref.source_revision_id,
        revision=source_ref.revision,
        artifact_revision_id=body.artifact_revision_id,
    )
    session.get = AsyncMock(return_value=source_row)
    held = [False]

    @asynccontextmanager
    async def transaction(
        *args: object, **kwargs: object
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        held[0] = True
        try:
            yield cast(AsyncSession, session), control, now
        finally:
            held[0] = False

    monkeypatch.setattr(module, "management_owner_transaction", transaction)
    metadata = AsyncMock(return_value=selected)
    monkeypatch.setattr(module, "native_cost_selection", metadata)
    monkeypatch.setattr(module, "require_resources", AsyncMock(return_value=(grant,)))
    monkeypatch.setattr(module, "source_artifact_reference", AsyncMock(return_value=body))
    monkeypatch.setattr(module, "heads", AsyncMock(return_value=(head,)))
    monkeypatch.setattr(module, "db_now", AsyncMock(side_effect=lambda _session: datetime.now(UTC)))
    monkeypatch.setattr(
        sources.artifacts, "revalidate_historical_artifact_reference", AsyncMock(return_value=())
    )
    monkeypatch.setattr(
        sources.freshness, "revalidate_historical_references", AsyncMock(return_value=())
    )
    monkeypatch.setattr(
        sources.freshness,
        "capture_plan_heads_locked",
        AsyncMock(return_value=(QualifiedFreshness(source_ref.source_id, policy, None, True),)),
    )
    return SimpleNamespace(
        reader=value,
        scope=scope,
        owner=owner,
        selected=selected,
        metadata=metadata,
        transaction=transaction,
        held=held,
        header=header,
        control=control,
        session=session,
        artifact=artifact,
    )


async def test_real_private_descriptor_and_envelope_read_outside_lock_without_current_goal_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = await supplied_case(tmp_path, monkeypatch)
    original = cast(CycleModelReader, value.reader).evidence.load

    async def read(reference: ArtifactRef) -> ModelEvidence:
        assert not value.held[0]
        return await original(reference)

    monkeypatch.setattr(value.reader.evidence, "load", read)
    result = await value.reader.read(
        value.scope,
        value.owner,
        value.selected.action.proposal.action_id,
        end_us=clock_us() + 30_000_000,
    )
    assert result.fact is not None and result.fact.billing == "known"
    assert not value.reader.pending_owners()


async def test_source_denial_before_any_descriptor_or_model_private_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus.company.brain.scope_support import BrainDeniedError

    value = await supplied_case(tmp_path, monkeypatch)
    denied = AsyncMock(side_effect=BrainDeniedError("supplied revoked current source grant"))
    monkeypatch.setattr(module, "require_resources", denied)
    private = AsyncMock(side_effect=AssertionError("private bytes before source authority"))
    monkeypatch.setattr(value.reader.evidence, "load", private)
    monkeypatch.setattr(value.reader.planning.blobs, "read", private)
    result = await value.reader.read(
        value.scope,
        value.owner,
        value.selected.action.proposal.action_id,
        end_us=clock_us() + 30_000_000,
    )
    assert result.fact is None and result.blockers == ("source_proof_unavailable",)
    private.assert_not_awaited()


async def test_caller_cancel_keeps_actual_private_read_owner_and_cannot_adopt_late_fact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    value = await supplied_case(tmp_path, monkeypatch)
    concrete = cast(CycleModelReader, value.reader)
    original = concrete.evidence.load
    entered, finish = asyncio.Event(), asyncio.Event()

    async def blocked(reference: ArtifactRef) -> ModelEvidence:
        entered.set()
        await finish.wait()
        return await original(reference)

    monkeypatch.setattr(concrete.evidence, "load", blocked)
    caller = asyncio.create_task(
        concrete.read(
            value.scope,
            value.owner,
            value.selected.action.proposal.action_id,
            end_us=clock_us() + 30_000_000,
        )
    )
    await asyncio.wait_for(entered.wait(), 2)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    pending = concrete.pending_owners()
    assert pending and not all(row.done() for row in pending)
    finish.set()
    await asyncio.gather(*pending)
    assert not concrete.pending_owners() and caller.cancelled()


async def test_original_deadline_denies_late_private_result_but_retains_its_actual_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    value = await supplied_case(tmp_path, monkeypatch)
    concrete = cast(CycleModelReader, value.reader)
    original = concrete.evidence.load
    entered, finish = asyncio.Event(), asyncio.Event()

    async def blocked(reference: ArtifactRef) -> ModelEvidence:
        entered.set()
        await finish.wait()
        return await original(reference)

    monkeypatch.setattr(concrete.evidence, "load", blocked)
    end_us = clock_us() + 5_000_000
    caller = asyncio.create_task(
        concrete.read(
            value.scope,
            value.owner,
            value.selected.action.proposal.action_id,
            end_us=end_us,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), max(0, end_us - clock_us()) / 1_000_000)
        with pytest.raises(TimeoutError):
            await caller
        pending = concrete.pending_owners()
        assert pending
        finish.set()
        await asyncio.gather(*pending)
        assert not concrete.pending_owners()
    finally:
        finish.set()
        if not caller.done():
            caller.cancel()
        await asyncio.gather(caller, return_exceptions=True)
        pending = concrete.pending_owners()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


async def test_other_model_roles_without_saved_header_do_not_read_private_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await supplied_case(tmp_path, monkeypatch)
    concrete = cast(CycleModelReader, value.reader)
    other = concrete.admission.slots[1]
    selected = value.selected.model_copy(
        update={
            "directory": value.selected.directory.model_copy(update={"task_id": other.work.task_id})
        }
    )
    value.metadata.return_value = selected
    private = AsyncMock(side_effect=AssertionError("C has no approved saved-header codec"))
    monkeypatch.setattr(concrete.evidence, "load", private)
    result = await concrete.read(
        value.scope, value.owner, selected.action.proposal.action_id, end_us=clock_us() + 30_000_000
    )
    assert result.fact is None and result.blockers == ("source_proof_unavailable",)
    private.assert_not_awaited()


async def test_current_owner_change_denies_before_private_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = await supplied_case(tmp_path, monkeypatch)
    concrete = cast(CycleModelReader, value.reader)
    value.control.owner_id = UUID(int=9999)
    private = AsyncMock(side_effect=AssertionError("private read after owner change"))
    monkeypatch.setattr(concrete.evidence, "load", private)
    with pytest.raises(ValueError):
        await concrete.read(
            value.scope,
            value.owner,
            value.selected.action.proposal.action_id,
            end_us=clock_us() + 30_000_000,
        )
    private.assert_not_awaited()


async def test_actual_native_row_projection_has_no_pydantic_schema_kwargs() -> None:
    from unittest.mock import MagicMock

    from nexus.company.directory_models import RegisteredWork
    from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
    from nexus.execution.runtime_support import registration_digest
    from nexus.harness.journal_models import CostHold, JournalAction
    from nexus.tests.unit.test_cycle_model_facts import case as native_case

    value = native_case()
    current, reg = value.work, value.work.registration
    raw = ExecutionWork(
        company_id=current.company_id,
        task_id=reg.work.task_id,
        trace_id=reg.work.trace_id,
        actor_id=current.actor_id,
        workspace_id=current.workspace_id,
        parent_task_id=current.parent_task_id,
        run_id=reg.run_id,
        registration_json=reg.model_dump_json(),
        registration_hash=registration_digest(reg),
        workflow_name=reg.workflow_name,
        workflow_version=reg.workflow_version,
        model_profile=reg.model_profile,
        model_registry_version=reg.model_registry_version,
        state=current.state,
        fence=current.fence,
        worker_id=None,
        lease_principal_id=None,
        lease_until=None,
        lease_mode=None,
        segment_number=current.segment_number,
        segment_id=current.segment_id,
        waiting_action_id=None,
        **{
            kind + "_" + suffix: getattr(parent, kind)
            for kind in type(reg.quota).model_fields
            for suffix, parent in (
                ("limit", reg.quota),
                ("used", current.counters),
                ("delegated", current.delegated),
            )
        },
    )
    proposal = value.action.proposal
    action = JournalAction(
        id=proposal.action_id,
        company_id=proposal.company_id,
        task_id=proposal.task_id,
        trace_id=proposal.trace_id,
        proposal_json=proposal.model_dump_json(),
        proposal_hash=value.action.proposal_hash,
        state=value.action.state.value,
        approval_json=value.action.approval.model_dump_json() if value.action.approval else None,
        consumed_at=value.action.consumed_at,
    )
    assert value.intent
    intent = EffectIntent(
        **value.intent.model_dump(exclude={"schema_version", "receipt", "verification"}),
        receipt_json=value.intent.receipt.model_dump_json() if value.intent.receipt else None,
        verification_json=None,
    )
    rows = {
        JournalAction: action,
        RegisteredWork: value.registered,
        ExecutionWork: raw,
        EffectIntent: intent,
        ExecutionAttempt: value.attempt,
        CostHold: value.hold,
    }
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(side_effect=lambda entity, _key: rows[entity])
    result = await module.native_cost_selection(
        cast(AsyncSession, session), proposal.company_id, proposal.action_id
    )
    assert result.directory.work == current and result.hold and value.hold
    assert result.hold.native_data().actual_usd == value.hold.actual_usd
    assert result.directory.directory_data().root_task_id == value.registered.root_task_id


async def test_crossed_native_proposal_hash_denies_before_any_private_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = await supplied_case(tmp_path, monkeypatch)
    value.metadata.return_value = value.selected.model_copy(
        update={"action": value.selected.action.model_copy(update={"proposal_hash": "0" * 64})}
    )
    private = AsyncMock(side_effect=AssertionError("crossed native action cannot disclose files"))
    monkeypatch.setattr(value.reader.evidence, "load", private)
    monkeypatch.setattr(value.reader.planning.blobs, "read", private)
    result = await value.reader.read(
        value.scope,
        value.owner,
        value.selected.action.proposal.action_id,
        end_us=clock_us() + 30_000_000,
    )
    assert result.fact is None and result.blockers == ("source_proof_unavailable",)
    private.assert_not_awaited()
