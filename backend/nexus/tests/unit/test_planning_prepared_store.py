"""Actual private blob I/O; auth/SQL/source delivery is supplied, not PostgreSQL proof.

Cohesion exception: the shared complete native fixture and finite owner/actor/worker
I/O boundaries stay together; none of these supplied transports qualify PostgreSQL.
"""

import asyncio
import os
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.builder.contained_query import clock_us
from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.access_contracts import ResourceGeneration
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.base import BrainReadScope, SourceTime
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.source_models import BrainSourceRevision
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.contracts.work import WorkItem
from nexus.company.management import planning_prepared_checks as checks
from nexus.company.management import planning_prepared_store as module
from nexus.company.management.base import RevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.goals import DueIntent, GoalDefinition, GoalMetric, UnknownBaseline
from nexus.company.management.governance_models import ManagementGoalHead, ManagementGoalRevision
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.owner_view_sources import OwnerViewSources
from nexus.company.management.plan_models import ManagementPlanHead
from nexus.company.management.plan_registration import registration
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding, PlanSourceFreshness
from nexus.company.management.planning_content import planning_schema
from nexus.company.management.planning_intent import (
    PreparedPlanningRequest,
    prepare_planning_request,
)
from nexus.company.management.planning_prepared_contracts import (
    PlanningPreparedRef,
    encode_prepared,
)
from nexus.company.management.planning_prepared_store import PlanningPreparedStore
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionLease
from nexus.execution.runtime_models import ExecutionWork
from nexus.execution.runtime_support import registration_digest
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.harness.model_authorizer_contracts import model_action_parameters
from nexus.tests.unit.test_company_brain_context_render import material
from nexus.tests.unit.test_company_planning_intent import prepared_inputs
from nexus.tests.unit.test_planning_proposal_bridge import template


@dataclass
class Fixture:
    store: PlanningPreparedStore
    prepared: PreparedPlanningRequest
    lease: ExecutionLease
    owner: VerifiedIdentity
    scope: CompanyControlScope
    session: AsyncSession
    rows: dict[type[object], object]
    current: CurrentPlanBinding
    revoked: bool = False


def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Fixture:
    """Real immutable rows; current auth and SQL delivery are explicitly supplied."""
    call, context, binding, scope, recipe, lease = prepared_inputs()
    now = datetime.now(UTC)
    owner = VerifiedIdentity(principal_id=UUID(int=99), workspace_id=scope.workspace_id)
    goal = GoalDefinition(
        company_id=call.company_id,
        goal_id=binding.goal.goal_id,
        owner_id=owner.principal_id,
        title="Review a Nexus plan",
        mandate=RevisionRef(
            company_id=call.company_id, revision_id=UUID(int=100), version="v1", sha256="a" * 64
        ),
        metrics=(
            GoalMetric(
                company_id=call.company_id,
                metric_id="drafts",
                unit="count",
                comparator="ge",
                target=Decimal(1),
                baseline=UnknownBaseline(reason="No measured result"),
            ),
        ),
        due=DueIntent(
            source_time=SourceTime(precision="unknown", value=None, basis="Not scheduled")
        ),
    )
    goal_ref = binding.goal.model_copy(update={"sha256": canonical_sha256(goal)})
    binding = binding.model_copy(
        update={"goal": goal_ref, "expected_plan_revision_id": UUID(int=40)}
    )
    call = call.model_copy(
        update={"output_schema": planning_schema(binding, manifest=context.manifest)}
    )
    prepared = prepare_planning_request(call, context, binding, scope=scope, input_recipe=recipe)
    base = template().base_plan.payload.children[0]
    run = base.binding.model_copy(
        update={
            "company_id": call.company_id,
            "task_id": lease.task_id,
            "trace_id": lease.trace_id,
            "actor_id": lease.actor_id,
            "workspace_id": lease.workspace_id,
            "run_id": lease.run_id,
            "workflow_name": "management.planning.v1",
            "workflow_version": lease.workflow_version,
            "model_profile": recipe.profile,
            "model_registry_version": call.registry_revision,
        }
    )
    child = base.model_copy(
        update={
            "binding": run,
            "quota": AttemptQuota(
                model_requests=1, tool_attempts=0, rework_rounds=0, plan_revisions=0
            ),
        }
    )
    item = WorkItem(
        company_id=call.company_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        goal_id=goal.goal_id,
        department="management",
        title="Prepare planning input",
        acceptance=("reviewable",),
        budget_usd=child.allocation_usd,
    )
    registered = registration(run, item, child.quota)
    work = ExecutionWork(
        company_id=call.company_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        actor_id=call.actor_id,
        workspace_id=lease.workspace_id,
        run_id=lease.run_id,
        parent_task_id=None,
        workflow_name=run.workflow_name,
        workflow_version=run.workflow_version,
        model_profile=run.model_profile,
        model_registry_version=call.registry_revision,
        registration_json=registered.model_dump_json(),
        registration_hash=registration_digest(registered),
        state="running",
        fence=lease.fence,
        segment_number=1,
        segment_id=lease.segment_id,
        worker_id=lease.worker_id,
        lease_principal_id=lease.actor_id,
        lease_until=lease.expires_at,
        lease_mode="execute",
        waiting_action_id=None,
        **{
            f"{kind}_{suffix}": 0
            for kind in AttemptQuota.model_fields
            for suffix in ("used", "delegated")
        },
        **{f"{kind}_limit": getattr(child.quota, kind) for kind in AttemptQuota.model_fields},
    )
    current = CurrentPlanBinding(
        company_id=call.company_id,
        plan=PlanRevisionRef(
            company_id=call.company_id,
            plan_id=binding.plan_id,
            plan_revision_id=UUID(int=40),
            revision=1,
            sha256="b" * 64,
        ),
        child=child,
        work=item,
        work_sha256=work.registration_hash,
        procedure_id=UUID(int=41),
    )
    control = CompanyControl(
        company_id=call.company_id,
        owner_id=owner.principal_id,
        policy_version="policy-v1",
        price_version=call.price_version,
        paused=False,
        daily_cap_usd=Decimal(5),
        work_cap_usd=Decimal(1),
    )
    rows: dict[type[object], object] = {
        ExecutionWork: work,
        ManagementGoalHead: ManagementGoalHead(
            company_id=call.company_id,
            goal_id=goal.goal_id,
            current_revision_id=goal_ref.revision_id,
            active=True,
        ),
        ManagementGoalRevision: ManagementGoalRevision(
            company_id=call.company_id,
            goal_id=goal.goal_id,
            revision_id=goal_ref.revision_id,
            version=goal_ref.version,
            sha256=goal_ref.sha256,
            payload_json=goal.model_dump_json(),
            recorded_by=owner.principal_id,
            recorded_at=now,
        ),
        ManagementPlanHead: ManagementPlanHead(
            company_id=call.company_id,
            plan_id=binding.plan_id,
            goal_id=goal.goal_id,
            current_revision_id=binding.expected_plan_revision_id,
        ),
        BrainSourceRevision: BrainSourceRevision(
            company_id=call.company_id,
            source_id=context.manifest.source_heads[0].source_id,
            source_revision_id=context.manifest.source_heads[0].current.source_revision_id,
            revision=context.manifest.source_heads[0].current.revision,
            artifact_revision_id=material().record.artifact.artifact_revision_id,
        ),
    }
    fake = MagicMock(spec=AsyncSession)
    fake.in_transaction.return_value = True
    fake.get = AsyncMock(side_effect=lambda model, key: rows.get(model))
    session = cast(AsyncSession, fake)
    factory = cast(async_sessionmaker[AsyncSession], MagicMock())
    blobs = ProtectedBlobStore(tmp_path / "prepared", storage_symbol="planning.prepared.v1")
    artifacts = BoundedArtifactReader(
        factory, ProtectedBlobStore(tmp_path / "source", storage_symbol="sources")
    )
    monkeypatch.setattr(artifacts, "revalidate_artifact_reference", AsyncMock())
    sources = OwnerViewSources(artifacts, cast(PlanSourceFreshness, AsyncMock()))
    fixture = Fixture(
        PlanningPreparedStore(factory, blobs, sources, recipe),
        prepared,
        lease,
        owner,
        CompanyControlScope(
            company_id=call.company_id,
            principal_id=owner.principal_id,
            operation_id=UUID(int=101),
            trace_id=UUID(int=102),
        ),
        session,
        rows,
        current,
    )

    @asynccontextmanager
    async def transaction(
        factory: async_sessionmaker[AsyncSession],
        actual: BrainReadScope,
        identity: VerifiedIdentity,
        *,
        owner: bool = False,
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        assert actual.principal_id == identity.principal_id
        assert identity == fixture.owner if owner else identity.principal_id == lease.actor_id
        yield session, control, now

    async def grant(
        session: AsyncSession,
        actual: BrainReadScope,
        ids: tuple[UUID, ...],
        now: datetime,
    ) -> tuple[ResourceGeneration, ...]:
        assert actual.principal_id in (fixture.owner.principal_id, lease.actor_id)
        if fixture.revoked:
            raise ValueError("supplied actual READ revoked")
        return prepared.context.manifest.contributors

    monkeypatch.setattr(module, "brain_transaction", transaction)
    monkeypatch.setattr(
        ManagementPlanStore,
        "current_binding",
        AsyncMock(side_effect=lambda *args: fixture.current),
    )
    monkeypatch.setattr(checks, "db_clock", AsyncMock(return_value=now))
    monkeypatch.setattr(module, "db_clock", AsyncMock(return_value=now))
    monkeypatch.setattr(checks, "require_resources", grant)
    monkeypatch.setattr(checks, "heads", AsyncMock(return_value=context.manifest.source_heads))
    monkeypatch.setattr(
        checks, "source_artifact_reference", AsyncMock(return_value=material().record.artifact)
    )
    monkeypatch.setattr(
        checks,
        "reference_sources",
        AsyncMock(
            return_value=(
                tuple(row.source_id for row in context.manifest.source_heads),
                tuple(row.resource_id for row in context.manifest.contributors),
            )
        ),
    )
    return fixture


def pending(f: Fixture, reference: PlanningPreparedRef) -> None:
    call = f.prepared.request
    conditions = tuple(
        ResourceRevision(
            resource=f"brain.resource:{row.resource_id}", revision=f"acl:{row.generation}"
        )
        for row in f.prepared.context.manifest.contributors
    ) + tuple(
        ResourceRevision(
            resource=f"brain.source:{row.source_id}",
            revision=f"head:{row.generation}:{row.current.source_revision_id}",
        )
        for row in f.prepared.context.manifest.source_heads
    )
    proposal = ActionProposal(
        company_id=call.company_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        actor_id=call.actor_id,
        action_id=call.action_id,
        revision=1,
        tool="model.request.v1",
        tool_version="v1",
        resource=f"model:{call.registry_id}",
        parameters=model_action_parameters(call, f.prepared.input_recipe),
        preconditions=(*conditions, reference.condition),
        policy_version="policy-v1",
        price_version=call.price_version,
        estimated_cost_usd="0.01",
    )
    f.rows[JournalAction] = JournalAction(
        id=call.action_id,
        company_id=call.company_id,
        task_id=call.task_id,
        trace_id=call.trace_id,
        proposal_json=proposal.model_dump_json(),
        proposal_hash=action_hash(proposal),
        state="awaiting_approval",
        consumed_at=None,
    )


async def test_owner_actor_and_worker_load_exact_input_without_impersonation_or_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = setup(tmp_path, monkeypatch)
    end = clock_us() + 30_000_000
    reference = await f.store.save(f.scope, f.owner, f.prepared, end_us=end)
    assert JournalAction not in f.rows  # Saving approves/authorizes/queues nothing.
    assert await f.store.save(f.scope, f.owner, f.prepared, end_us=end) == reference
    pending(f, reference)
    owner = await f.store.load_owner(f.scope, f.owner, f.prepared.request.action_id, end_us=end)
    actor_identity = VerifiedIdentity(
        principal_id=f.lease.actor_id, workspace_id=f.lease.workspace_id
    )
    actor = await f.store.load_actor(
        f.prepared.scope, actor_identity, f.prepared.request.action_id, end_us=end
    )
    assert owner.prepared == actor.prepared == f.prepared
    assert 0 < owner.read_end_us <= end
    assert 0 < actor.read_end_us <= end
    with pytest.raises(ValueError):
        await f.store.load_worker(f.lease, actor_identity, f.prepared.request.action_id, end_us=end)
    row = cast(JournalAction, f.rows[JournalAction])
    row.state, row.consumed_at = "authorized", datetime.now(UTC)
    assert (
        await f.store.load_worker(f.lease, actor_identity, f.prepared.request.action_id, end_us=end)
    ).prepared == f.prepared
    assert not f.store.pending_owners()


async def test_source_revocation_denies_before_any_private_body_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = setup(tmp_path, monkeypatch)
    end = clock_us() + 30_000_000
    reference = await f.store.save(f.scope, f.owner, f.prepared, end_us=end)
    pending(f, reference)
    f.revoked = True
    actual = f.store.blobs.read
    seen: list[str] = []

    async def read(ref: ArtifactRevisionRef) -> bytes:
        seen.append(ref.revision)
        return await actual(ref)

    monkeypatch.setattr(f.store.blobs, "read", read)
    with pytest.raises(ValueError):
        await f.store.load_owner(f.scope, f.owner, f.prepared.request.action_id, end_us=end)
    assert seen == ["planning-prepared-descriptor-v1"]


async def test_cancel_retains_actual_blob_thread_and_never_publishes_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = setup(tmp_path, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    original = f.store.blobs.save

    async def blocked(ref: ArtifactRevisionRef, raw: bytes) -> None:
        entered.set()
        await asyncio.to_thread(lambda: release.wait(3))
        await original(ref, raw)

    monkeypatch.setattr(f.store.blobs, "save", blocked)
    caller = asyncio.create_task(
        f.store.save(f.scope, f.owner, f.prepared, end_us=clock_us() + 30_000_000)
    )
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        caller.cancel("original store caller")
        with pytest.raises(asyncio.CancelledError, match="original store caller"):
            await caller
        assert f.store.pending_owners() and all(
            not task.cancelled() for task in f.store.pending_owners()
        )
        assert JournalAction not in f.rows
    finally:
        release.set()
        await asyncio.gather(caller, *f.store.pending_owners(), return_exceptions=True)
    assert not f.store.pending_owners()


async def test_real_actor_prepares_before_pending_then_reads_without_a_new_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = setup(tmp_path, monkeypatch)
    actor = VerifiedIdentity(principal_id=f.lease.actor_id, workspace_id=f.lease.workspace_id)
    end = clock_us() + 30_000_000
    reference = await f.store.save_worker(f.lease, actor, f.prepared, end_us=end)
    assert JournalAction not in f.rows
    pending(f, reference)
    work = cast(ExecutionWork, f.rows[ExecutionWork])
    work.state, work.lease_until, work.lease_principal_id = "awaiting_approval", None, None
    loaded = await f.store.load_actor(
        f.prepared.scope, actor, f.prepared.request.action_id, end_us=end
    )
    assert loaded.reference == reference and loaded.prepared == f.prepared
    assert cast(JournalAction, f.rows[JournalAction]).consumed_at is None
    with pytest.raises(ValueError):
        await f.store.load_worker(f.lease, actor, f.prepared.request.action_id, end_us=end)


async def test_target_plan_cas_is_independent_of_the_plan_registering_the_planner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = setup(tmp_path, monkeypatch)
    # Existing PlanningIntentCheck permits a distinct target plan with its actual CAS.
    f.current = f.current.model_copy(
        update={"plan": f.current.plan.model_copy(update={"plan_id": UUID(int=900)})}
    )
    reference = await f.store.save(f.scope, f.owner, f.prepared, end_us=clock_us() + 30_000_000)
    assert reference.action_id == f.prepared.request.action_id


@pytest.mark.parametrize("change", ("source", "goal", "target", "registration", "end"))
async def test_body_read_never_returns_after_current_source_native_or_original_end_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    f = setup(tmp_path, monkeypatch)
    end = clock_us() + 30_000_000
    reference = await f.store.save(f.scope, f.owner, f.prepared, end_us=end)
    pending(f, reference)
    original = f.store.blobs.read

    async def changed(ref: ArtifactRevisionRef) -> bytes:
        raw = await original(ref)
        if ref.revision == "planning-prepared-body-v1":
            if change == "source":
                f.revoked = True
            elif change == "goal":
                cast(ManagementGoalHead, f.rows[ManagementGoalHead]).active = False
            elif change == "target":
                cast(ManagementPlanHead, f.rows[ManagementPlanHead]).current_revision_id = UUID(
                    int=901
                )
            elif change == "registration":
                f.current = f.current.model_copy(
                    update={"work": f.current.work.model_copy(update={"acceptance": ("changed",)})}
                )
            else:
                monkeypatch.setattr(module, "clock_us", lambda: end)
                monkeypatch.setattr(
                    "nexus.company.management.planning_native_facts.clock_us", lambda: end
                )
        return raw

    monkeypatch.setattr(f.store.blobs, "read", changed)
    with pytest.raises((ValueError, TimeoutError)):
        await f.store.load_owner(f.scope, f.owner, f.prepared.request.action_id, end_us=end)


@pytest.mark.parametrize("change", ("hardlink", "writable", "bytes"))
async def test_actual_private_body_identity_modes_and_complete_bytes_are_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    f = setup(tmp_path, monkeypatch)
    end = clock_us() + 30_000_000
    reference = await f.store.save(f.scope, f.owner, f.prepared, end_us=end)
    pending(f, reference)
    body = encode_prepared(f.prepared)[1]
    path = f.store.blobs._path(body)
    if change == "hardlink":
        os.link(path, path.with_suffix(".alias"))
    elif change == "writable":
        path.chmod(0o600)
    else:
        path.chmod(0o600)
        path.write_bytes(b"x" * body.byte_length)
        path.chmod(0o400)
    with pytest.raises(ValueError):
        await f.store.load_owner(f.scope, f.owner, f.prepared.request.action_id, end_us=end)


@pytest.mark.parametrize("window", ("source", "lease"))
async def test_final_transaction_exit_cannot_outlive_actual_read_or_lease_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    window: str,
) -> None:
    f = setup(tmp_path, monkeypatch)
    end = clock_us() + 30_000_000
    reference = await f.store.save(f.scope, f.owner, f.prepared, end_us=end)
    pending(f, reference)
    current = [clock_us()]
    baseline = current[0]
    now = cast(ManagementGoalRevision, f.rows[ManagementGoalRevision]).recorded_at
    if window == "lease":
        f.lease = f.lease.model_copy(update={"expires_at": now + timedelta(seconds=1)})
        cast(ExecutionWork, f.rows[ExecutionWork]).lease_until = f.lease.expires_at
        action = cast(JournalAction, f.rows[JournalAction])
        action.state, action.consumed_at = "authorized", now
    body_seen = False
    original_read = f.store.blobs.read
    # This is the explicitly supplied transaction transport installed by setup().
    original_transaction = cast(
        Callable[..., AbstractAsyncContextManager[tuple[AsyncSession, CompanyControl, datetime]]],
        vars(module)["brain_transaction"],
    )

    async def grants(
        session: AsyncSession,
        scope: BrainReadScope,
        ids: tuple[UUID, ...],
        observed: datetime,
    ) -> tuple[ResourceGeneration, ...]:
        return tuple(
            row.model_copy(update={"expires_at": now + timedelta(seconds=1)})
            if window == "source"
            else row
            for row in f.prepared.context.manifest.contributors
        )

    async def read(ref: ArtifactRevisionRef) -> bytes:
        nonlocal body_seen
        value = await original_read(ref)
        body_seen = body_seen or ref.revision == "planning-prepared-body-v1"
        return value

    @asynccontextmanager
    async def transaction(
        factory: async_sessionmaker[AsyncSession],
        scope: BrainReadScope,
        identity: VerifiedIdentity,
        *,
        owner: bool = False,
    ) -> AsyncIterator[tuple[AsyncSession, CompanyControl, datetime]]:
        async with original_transaction(factory, scope, identity, owner=owner) as values:
            yield values
        if body_seen:
            current[0] = baseline + 2_000_000  # Same original window expires during final exit.

    monkeypatch.setattr(checks, "require_resources", grants)
    monkeypatch.setattr(module, "brain_transaction", transaction)
    monkeypatch.setattr(f.store.blobs, "read", read)
    monkeypatch.setattr(module, "clock_us", lambda: current[0])
    monkeypatch.setattr(
        "nexus.company.management.planning_native_facts.clock_us", lambda: current[0]
    )
    with pytest.raises(TimeoutError):
        if window == "source":
            await f.store.load_owner(f.scope, f.owner, f.prepared.request.action_id, end_us=end)
        else:
            identity = VerifiedIdentity(
                principal_id=f.lease.actor_id, workspace_id=f.lease.workspace_id
            )
            await f.store.load_worker(f.lease, identity, f.prepared.request.action_id, end_us=end)
