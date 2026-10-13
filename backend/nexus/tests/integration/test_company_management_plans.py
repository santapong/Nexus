"""Actual public-store approval/registration is atomic and permanently bounded.

This single assigned integration module exceeds the 400-line limit to retain
the coherent normal-migration store and shared-boundary failure matrix.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.source_models import BrainSourceHead
from nexus.company.contracts.knowledge import ArtifactRef
from nexus.company.contracts.results import ActionReceipt
from nexus.company.directory_contracts import MembershipChange
from nexus.company.directory_models import RegisteredWork
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.plan_models import (
    ManagementOwnerDecision,
    ManagementPlanTask,
    ManagementProcedure,
    ManagementRevisionEvent,
)
from nexus.company.management.plan_support import NamedPlanResource
from nexus.execution.effect_store import EffectStore
from nexus.execution.management_checks import current_accepted_work
from nexus.execution.runtime_models import ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import runtime_transaction
from nexus.harness.canonical import action_hash
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl, CostHold, JournalAction
from nexus.tests.integration.management_acceptance_fixture import issue_accepted_report_fixture
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, SOURCE, owner_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_plan_support import (
    DERIVED_RESOURCE,
    VERIFIER,
    authorized_action,
    configured_plan,
    derived_output,
    registered_freshness,
)
from nexus.tests.management_plan_support import plans_factory as plans_factory


async def _counts(factory: async_sessionmaker[AsyncSession]) -> tuple[int, ...]:
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        return tuple(
            [
                (await session.scalar(select(func.count()).select_from(row))) or 0
                for row in (
                    RegisteredWork,
                    ExecutionWork,
                    ManagementProcedure,
                    ManagementPlanTask,
                    ManagementOwnerDecision,
                    ManagementRevisionEvent,
                    ExecutionAttempt,
                )
            ]
        )


async def test_public_proposal_mints_no_work_and_exact_approval_replay_delegates_once(
    plans_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store, data = await configured_plan(plans_factory, tmp_path)
    proposed = await store.propose(
        control(), identity(OWNER), data, expected_current_revision_id=None
    )
    assert await _counts(plans_factory) == (0, 0, 0, 0, 0, 0, 0)
    result = await store.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=proposed.plan_revision_id,
    )
    assert result == proposed
    assert (
        await store.approve_and_register(
            control(),
            identity(OWNER),
            proposed.plan_revision_id,
            proposed.sha256,
            expected_current_revision_id=proposed.plan_revision_id,
        )
        == result
    )
    assert await _counts(plans_factory) == (3, 3, 1, 2, 1, 0, 0)
    async with plans_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        parent = await session.get(ExecutionWork, (COMPANY, data.procedure.binding.task_id))
        assert (
            parent is not None
            and parent.plan_revisions_used == 0
            and parent.model_requests_delegated == 2
        )
        bound = await store.current_binding(session, COMPANY, data.children[0].binding.task_id)
        assert (
            bound is not None
            and bound.work_sha256
            and bound.plan.plan_revision_id == proposed.plan_revision_id
        )


@pytest.mark.parametrize(
    "failure", ["hash", "cas", "owner", "member", "tool", "resource", "model", "recipe"]
)
async def test_actual_current_admission_failure_registers_no_partial_work(
    plans_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    failure: str,
) -> None:
    store, data = await configured_plan(plans_factory, tmp_path)
    proposed = await store.propose(
        control(), identity(OWNER), data, expected_current_revision_id=None
    )
    if failure == "member":
        await PersistentCompanyDirectory(plans_factory).set_membership(
            MembershipChange(
                company_id=COMPANY, principal_id=ACTOR, role="member", membership_active=False
            ),
            control(),
        )
    if failure in {"tool", "resource", "model", "recipe"}:
        field = {
            "tool": "tools",
            "resource": "resources",
            "model": "admitted_profiles",
            "recipe": "check_recipes",
        }[failure]
        store.catalog = store.catalog.model_copy(
            update={field: () if field in {"tools", "resources"} else frozenset()}
        )
    with pytest.raises(ValueError):
        await store.approve_and_register(
            control(ACTOR) if failure == "owner" else control(),
            identity(ACTOR) if failure == "owner" else identity(OWNER),
            proposed.plan_revision_id,
            "f" * 64 if failure == "hash" else proposed.sha256,
            expected_current_revision_id=uuid4() if failure == "cas" else proposed.plan_revision_id,
        )
    assert await _counts(plans_factory) == (0, 0, 0, 0, 0, 0, 0)


async def test_new_plan_ids_reuse_one_root_and_owner_revision_quota_without_execution_attempts(
    plans_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store, data = await configured_plan(plans_factory, tmp_path)
    previous = await store.propose(
        control(), identity(OWNER), data, expected_current_revision_id=None
    )
    await store.approve_and_register(
        control(),
        identity(OWNER),
        previous.plan_revision_id,
        previous.sha256,
        expected_current_revision_id=previous.plan_revision_id,
    )
    for _ in range(2):
        new = data.model_copy(update={"plan": data.plan.model_copy(update={"plan_id": uuid4()})})
        proposed = await store.propose(
            control(), identity(OWNER), new, expected_current_revision_id=None
        )
        await store.approve_and_register(
            control(),
            identity(OWNER),
            proposed.plan_revision_id,
            proposed.sha256,
            expected_current_revision_id=proposed.plan_revision_id,
        )
        previous = proposed
    denied = data.model_copy(update={"plan": data.plan.model_copy(update={"plan_id": uuid4()})})
    proposed = await store.propose(
        control(), identity(OWNER), denied, expected_current_revision_id=None
    )
    with pytest.raises(ValueError):
        await store.approve_and_register(
            control(),
            identity(OWNER),
            proposed.plan_revision_id,
            proposed.sha256,
            expected_current_revision_id=proposed.plan_revision_id,
        )
    assert await _counts(plans_factory) == (3, 3, 1, 6, 3, 2, 0)


async def test_second_child_registration_failure_rolls_back_first_child_and_revision(
    plans_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store, data = await configured_plan(plans_factory, tmp_path)
    first = await store.propose(control(), identity(OWNER), data, expected_current_revision_id=None)
    await store.approve_and_register(
        control(),
        identity(OWNER),
        first.plan_revision_id,
        first.sha256,
        expected_current_revision_id=first.plan_revision_id,
    )
    children = tuple(
        row.model_copy(
            update={
                "binding": row.binding.model_copy(
                    update={"task_id": uuid4(), "trace_id": uuid4(), "run_id": uuid4()}
                ),
                "allocation_usd": Decimal("0.4"),
            }
        )
        for row in data.children
    )
    items = tuple(
        row.model_copy(
            update={
                "task_id": child.binding.task_id,
                "trace_id": child.binding.trace_id,
                "budget_usd": child.allocation_usd,
            }
        )
        for row, child in zip(data.plan.items, children, strict=True)
    )
    edges = (
        data.verification[0].model_copy(
            update={
                "author_task_id": children[0].binding.task_id,
                "verifier_task_id": children[1].binding.task_id,
            }
        ),
    )
    changed = data.model_copy(
        update={
            "children": children,
            "verification": edges,
            "plan": data.plan.model_copy(update={"revision": 2, "items": items}),
        }
    )
    proposed = await store.propose(
        control(), identity(OWNER), changed, expected_current_revision_id=first.plan_revision_id
    )
    with pytest.raises(ValueError):
        await store.approve_and_register(
            control(),
            identity(OWNER),
            proposed.plan_revision_id,
            proposed.sha256,
            expected_current_revision_id=first.plan_revision_id,
        )
    assert await _counts(plans_factory) == (3, 3, 1, 2, 1, 0, 0)


async def test_revoke_retains_registered_work_and_prevents_reapproval_without_new_revision(
    plans_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store, data = await configured_plan(plans_factory, tmp_path)
    proposed = await store.propose(
        control(), identity(OWNER), data, expected_current_revision_id=None
    )
    await store.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=proposed.plan_revision_id,
    )
    await store.revoke(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=proposed.plan_revision_id,
    )
    assert await _counts(plans_factory) == (3, 3, 1, 2, 2, 0, 0)
    with pytest.raises(ValueError):
        await store.approve_and_register(
            control(),
            identity(OWNER),
            proposed.plan_revision_id,
            proposed.sha256,
            expected_current_revision_id=proposed.plan_revision_id,
        )


@pytest.mark.parametrize(
    "failure",
    [
        "none",
        "procedure",
        "missing_catalog",
        "plan",
        "mandate",
        "charter",
        "resource",
        "profile",
        "verifier_unbound",
        "dependency",
    ],
)
async def test_execute_claim_rechecks_actual_management_and_preserves_counters_on_denial(
    plans_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    failure: str,
) -> None:
    store, data = await configured_plan(plans_factory, tmp_path)
    if failure == "dependency":
        items = (
            data.plan.items[0],
            data.plan.items[1].model_copy(update={"depends_on": (data.plan.items[0].task_id,)}),
        )
        data = data.model_copy(
            update={"plan": data.plan.model_copy(update={"items": items}), "verification": ()}
        )
    proposed = await store.propose(
        control(), identity(OWNER), data, expected_current_revision_id=None
    )
    await store.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=proposed.plan_revision_id,
    )
    selected = (
        data.procedure.binding
        if failure == "procedure"
        else data.children[1].binding
        if failure in {"dependency", "verifier_unbound"}
        else data.children[0].binding
    )
    if failure == "plan":
        await store.revoke(
            control(),
            identity(OWNER),
            proposed.plan_revision_id,
            proposed.sha256,
            expected_current_revision_id=proposed.plan_revision_id,
        )
    elif failure == "mandate":
        await ManagementControlStore(plans_factory).revoke_mandate(
            control(), identity(OWNER), data.mandate
        )
    elif failure == "charter":
        await ManagementControlStore(plans_factory).revoke_charter(
            control(), identity(OWNER), data.charters[0]
        )
    elif failure == "resource":
        await ResourceAccessStore(plans_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=ACTOR,
                active=False,
                expected_generation=2,
            ),
        )
    catalog = (
        store.catalog.model_copy(update={"admitted_profiles": frozenset()})
        if failure == "profile"
        else store.catalog
    )
    execution = ExecutionStore(
        plans_factory, management_catalog=None if failure == "missing_catalog" else catalog
    )
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=selected.actor_id,
        task_id=selected.task_id,
        trace_id=selected.trace_id,
    )
    if failure == "none":
        lease = await execution.claim(scope, identity(selected.actor_id), uuid4())
        assert lease.actor_id == selected.actor_id
    else:
        with pytest.raises(ValueError):
            await execution.claim(scope, identity(selected.actor_id), uuid4())
        current = await execution.get(
            scope.model_copy(update={"principal_id": OWNER}), identity(OWNER)
        )
        assert (
            current.counters.model_requests == 0
            and current.segment_number == 0
            and current.fence == 0
        )


async def test_changed_existing_child_criteria_cannot_rebind_actual_registration(
    plans_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store, data = await configured_plan(plans_factory, tmp_path)
    first = await store.propose(control(), identity(OWNER), data, expected_current_revision_id=None)
    await store.approve_and_register(
        control(),
        identity(OWNER),
        first.plan_revision_id,
        first.sha256,
        expected_current_revision_id=first.plan_revision_id,
    )
    changed = data.model_copy(
        update={
            "plan": data.plan.model_copy(
                update={
                    "revision": 2,
                    "items": (
                        data.plan.items[0].model_copy(update={"acceptance": ("new-criteria",)}),
                        data.plan.items[1],
                    ),
                }
            )
        }
    )
    proposed = await store.propose(
        control(), identity(OWNER), changed, expected_current_revision_id=first.plan_revision_id
    )
    with pytest.raises(ValueError):
        await store.approve_and_register(
            control(),
            identity(OWNER),
            proposed.plan_revision_id,
            proposed.sha256,
            expected_current_revision_id=first.plan_revision_id,
        )
    assert await _counts(plans_factory) == (3, 3, 1, 2, 1, 0, 0)


async def test_equal_usd_display_scale_preserves_original_m1_registration_hash(
    plans_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    store, data = await configured_plan(plans_factory, tmp_path)
    first = await store.propose(control(), identity(OWNER), data, expected_current_revision_id=None)
    await store.approve_and_register(
        control(),
        identity(OWNER),
        first.plan_revision_id,
        first.sha256,
        expected_current_revision_id=first.plan_revision_id,
    )
    task_id = data.children[0].binding.task_id
    async with plans_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        original = await session.get(ExecutionWork, (COMPANY, task_id))
        assert original is not None
        original_hash = original.registration_hash
    children = tuple(
        row.model_copy(update={"allocation_usd": Decimal("0.200000")}) for row in data.children
    )
    items = tuple(
        row.model_copy(update={"budget_usd": Decimal("0.200000")}) for row in data.plan.items
    )
    changed = data.model_copy(
        update={
            "children": children,
            "plan": data.plan.model_copy(update={"revision": 2, "items": items}),
        }
    )
    proposed = await store.propose(
        control(), identity(OWNER), changed, expected_current_revision_id=first.plan_revision_id
    )
    await store.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=first.plan_revision_id,
    )
    async with plans_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        current = await store.current_binding(session, COMPANY, task_id)
        assert current is not None and current.work_sha256 == original_hash
    assert await _counts(plans_factory) == (3, 3, 1, 4, 2, 1, 0)


@pytest.mark.parametrize(
    "failure",
    ["none", "plan_revoked", "grant_expired_during_prepare", "tool", "version", "resource"],
)
async def test_effect_preparation_rechecks_management_and_retains_holds_on_denial(
    plans_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    failure: str,
) -> None:
    store, data = await configured_plan(plans_factory, tmp_path)
    proposed = await store.propose(
        control(), identity(OWNER), data, expected_current_revision_id=None
    )
    await store.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=proposed.plan_revision_id,
    )
    bound = data.children[0].binding
    execution = ExecutionStore(plans_factory, management_catalog=store.catalog)
    effects = EffectStore(plans_factory, management_catalog=store.catalog)
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=bound.actor_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
    )
    lease = await execution.claim(scope, identity(bound.actor_id), uuid4())
    action = await authorized_action(
        plans_factory,
        bound,
        tool="unregistered.tool" if failure == "tool" else "fake.internal.read.v1",
        version="v9" if failure == "version" else "v1",
        resource="unregistered.resource" if failure == "resource" else "company.report",
    )
    if failure == "plan_revoked":
        await store.revoke(
            control(),
            identity(OWNER),
            proposed.plan_revision_id,
            proposed.sha256,
            expected_current_revision_id=proposed.plan_revision_id,
        )
    if failure == "grant_expired_during_prepare":
        await ResourceAccessStore(plans_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=ACTOR,
                active=True,
                expected_generation=2,
                expires_at=datetime.now(UTC) + timedelta(seconds=0.2),
            ),
        )

    class SlowPreparation:
        async def validate(
            self,
            session: AsyncSession,
            control: CompanyControl,
            work: ExecutionWork,
            proposal: JournalAction,
            now: datetime,
        ) -> None:
            await session.execute(select(func.pg_sleep(0.35)))

    if failure == "none":
        start = await effects.begin(lease, identity(bound.actor_id), action.action_id)
        assert start.permit_external_call
        await store.revoke(
            control(),
            identity(OWNER),
            proposed.plan_revision_id,
            proposed.sha256,
            expected_current_revision_id=proposed.plan_revision_id,
        )
        receipt = ActionReceipt(
            company_id=COMPANY,
            receipt_id=uuid4(),
            action_id=action.action_id,
            task_id=bound.task_id,
            trace_id=bound.trace_id,
            proposal_hash=action_hash(action),
            outcome="succeeded",
            recorded_at=datetime.now(UTC),
        )
        await effects.record_receipt(lease, identity(bound.actor_id), receipt, actual_usd=None)
        assert not (
            await effects.begin(lease, identity(bound.actor_id), action.action_id)
        ).permit_external_call
    else:
        with pytest.raises(ValueError):
            await effects.begin(
                lease,
                identity(bound.actor_id),
                action.action_id,
                before_intent=SlowPreparation()
                if failure == "grant_expired_during_prepare"
                else None,
            )
        current = await execution.get(scope, identity(bound.actor_id))
        assert current.counters.tool_attempts == 0
    async with plans_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        hold = await session.get(CostHold, action.action_id)
        assert hold is not None and hold.amount_usd == Decimal("0.030000")
        assert hold.state == ("unknown" if failure == "none" else "held")


@pytest.mark.parametrize(
    "failure",
    [
        "none",
        "input_revoked",
        "input_stale",
        "receipt_hash",
        "missing_reader",
        "unqualified_null_ttl",
    ],
)
async def test_verification_trigger_requires_complete_current_derived_output_provenance(
    plans_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    failure: str,
) -> None:
    # Keep the public effect/receipt and derived grant transitions in one fixture scenario.
    store, data = await configured_plan(plans_factory, tmp_path)
    artifact = await derived_output(plans_factory, tmp_path)
    freshness = registered_freshness(plans_factory)
    store.source_freshness = freshness
    store.catalog = store.catalog.model_copy(
        update={
            "resources": (
                NamedPlanResource(
                    symbol="company.report",
                    resource=ResourceRef(company_id=COMPANY, resource_id=DERIVED_RESOURCE),
                ),
            )
        }
    )
    proposed = await store.propose(
        control(), identity(OWNER), data, expected_current_revision_id=None
    )
    await store.approve_and_register(
        control(),
        identity(OWNER),
        proposed.plan_revision_id,
        proposed.sha256,
        expected_current_revision_id=proposed.plan_revision_id,
    )
    author, verifier = (row.binding for row in data.children)
    blobs = ProtectedBlobStore(tmp_path, storage_symbol="fixture.blobs.v1")
    reader = BoundedArtifactReader(plans_factory, blobs)
    execution = ExecutionStore(
        plans_factory,
        management_catalog=store.catalog,
        management_artifacts=None if failure == "missing_reader" else reader,
        management_freshness=freshness,
    )
    author_scope = LedgerScope(
        company_id=COMPANY,
        principal_id=author.actor_id,
        task_id=author.task_id,
        trace_id=author.trace_id,
    )
    lease = await execution.claim(author_scope, identity(author.actor_id), uuid4())
    action = await authorized_action(plans_factory, author)
    effects = EffectStore(
        plans_factory,
        management_catalog=store.catalog,
        management_artifacts=reader,
        management_freshness=freshness,
    )
    await effects.begin(lease, identity(author.actor_id), action.action_id)
    output = ArtifactRef(
        company_id=COMPANY,
        artifact_id=artifact.artifact_id,
        revision=artifact.revision,
        reference="fixture-derived-plan",
        sha256="f" * 64 if failure == "receipt_hash" else artifact.sha256,
    )
    await effects.record_receipt(
        lease,
        identity(author.actor_id),
        ActionReceipt(
            company_id=COMPANY,
            receipt_id=uuid4(),
            action_id=action.action_id,
            task_id=author.task_id,
            trace_id=author.trace_id,
            proposal_hash=action_hash(action),
            outcome="succeeded",
            recorded_at=datetime.now(UTC),
            artifacts=(output,),
        ),
        actual_usd=Decimal(0),
    )
    if failure == "input_revoked":
        await ResourceAccessStore(plans_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=VERIFIER,
                active=False,
                expected_generation=2,
            ),
        )
    elif failure in {"input_stale", "unqualified_null_ttl"}:
        async with plans_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            head = await session.get(BrainSourceHead, (COMPANY, SOURCE))
            assert head is not None
            head.fresh_until = (
                None
                if failure == "unqualified_null_ttl"
                else datetime.now(UTC) + timedelta(seconds=0.02)
            )
        await asyncio.sleep(0.03)
    verifier_scope = LedgerScope(
        company_id=COMPANY,
        principal_id=verifier.actor_id,
        task_id=verifier.task_id,
        trace_id=verifier.trace_id,
    )
    if failure == "none":
        assert (
            await execution.claim(verifier_scope, identity(verifier.actor_id), uuid4())
        ).actor_id == VERIFIER
    else:
        with pytest.raises(ValueError):
            await execution.claim(verifier_scope, identity(verifier.actor_id), uuid4())


@pytest.mark.parametrize(
    "failure", ["none", "invalidated", "proof_grant", "unknown_proof_ttl", "mandate"]
)
async def test_real_public_acceptance_enables_dependency_with_current_complete_proof(
    plans_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    failure: str,
) -> None:
    scenario, record = await issue_accepted_report_fixture(
        plans_factory, tmp_path, with_dependent=True
    )
    if failure == "invalidated":
        await scenario.store.invalidate(
            control(), identity(OWNER), record.acceptance_id, "source_changed"
        )
    elif failure == "proof_grant":
        await ResourceAccessStore(plans_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=UUID(int=301)),
                principal_id=ACTOR,
                active=False,
                expected_generation=1,
            ),
        )
    elif failure == "unknown_proof_ttl":
        async with plans_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            head = await session.get(BrainSourceHead, (COMPANY, UUID(int=300)))
            assert head is not None
            head.fresh_until = None
    elif failure == "mandate":
        await ManagementControlStore(plans_factory).revoke_mandate(
            control(), identity(OWNER), scenario.payload.mandate
        )
    bound = scenario.payload.children[2].binding
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=bound.actor_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
    )
    async with runtime_transaction(plans_factory, scope, identity(bound.actor_id)) as (
        session,
        current,
        _,
    ):
        reader = await session.get(ExecutionWork, (COMPANY, bound.task_id))
        dependency = await session.get(ExecutionWork, (COMPANY, record.target.author.task_id))
        assert reader is not None and dependency is not None
        observed = await current_accepted_work(
            session,
            current,
            reader,
            dependency,
            identity(bound.actor_id),
            scenario.artifacts,
            scenario.freshness,
        )
        assert observed == (record if failure == "none" else None)
    if failure == "none":
        assert (
            await scenario.execution.claim(scope, identity(bound.actor_id), uuid4())
        ).actor_id == bound.actor_id
    else:
        with pytest.raises(ValueError):
            await scenario.execution.claim(scope, identity(bound.actor_id), uuid4())
