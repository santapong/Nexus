"""Real owner approval and stored zero-model ancestry, without sandbox or provider effects."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.contracts.work import WorkItem
from nexus.company.control_store import CompanyControls
from nexus.company.directory_contracts import WorkRegistration
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.plan_registration import registration
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import PlanPayload
from nexus.execution.effect_store import EffectStore
from nexus.execution.native_profile_checks import require_native_ancestry
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import registration_digest, runtime_transaction
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl, CostHold, JournalAction
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_plan_support import authorized_action
from nexus.tests.native_execution_profile_fixture import native_factory as native_factory
from nexus.tests.native_execution_profile_fixture import native_plan


async def _approve(store: ManagementPlanStore, data: PlanPayload) -> None:
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


@pytest.mark.parametrize(
    "failure", ["none", "model_kind", "model_tool", "source", "charter", "pause"]
)
async def test_native_empty_registry_preserves_actual_approval_source_and_unconfirmed_holds(
    native_factory: async_sessionmaker[AsyncSession], tmp_path: Path, failure: str
) -> None:
    # Keep current revocation, issued-intent counters and unknown billing in one real scenario.
    store, data = await native_plan(native_factory, tmp_path)
    assert store.catalog.models.models == () and store.catalog.model_observations == ()
    await _approve(store, data)
    bound = data.children[0].binding
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=bound.actor_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
    )
    runtime = ExecutionStore(native_factory, management_catalog=store.catalog)
    effects = EffectStore(native_factory, management_catalog=store.catalog)
    lease = await runtime.claim(scope, identity(bound.actor_id), uuid4())
    before = await runtime.get(scope, identity(bound.actor_id))
    action = await authorized_action(
        native_factory,
        bound,
        tool="model.request.v1" if failure == "model_tool" else "company.builder.run.v1",
        resource="model:missing" if failure == "model_tool" else "company.report",
    )
    if failure == "source":
        await ResourceAccessStore(native_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=bound.actor_id,
                active=False,
                expected_generation=2,
            ),
        )
    elif failure == "charter":
        await ManagementControlStore(native_factory).revoke_charter(
            control(), identity(OWNER), data.children[0].charter
        )
    elif failure == "pause":
        await CompanyControls(native_factory).set_paused_registered(
            control(), identity(OWNER), True
        )
    if failure == "none":
        start = await effects.begin(lease, identity(bound.actor_id), action.action_id)
        assert start.permit_external_call
        replay = await effects.begin(lease, identity(bound.actor_id), action.action_id)
        assert not replay.permit_external_call
    else:
        with pytest.raises(ValueError):
            await effects.begin(
                lease,
                identity(bound.actor_id),
                action.action_id,
                kind="model_requests" if failure == "model_kind" else "tool_attempts",
            )
    async with native_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        child = await session.get(ExecutionWork, (COMPANY, bound.task_id))
        parent = await session.get(ExecutionWork, (COMPANY, data.procedure.binding.task_id))
        intent = await session.get(EffectIntent, (COMPANY, action.action_id))
        hold = await session.get(CostHold, action.action_id)
        assert child is not None and parent is not None and hold is not None
        assert child.registration_hash == registration_digest(before.registration)
        assert (
            child.model_requests_limit
            == child.model_requests_used
            == parent.model_requests_limit
            == 0
        )
        assert child.tool_attempts_used == (1 if failure == "none" else 0)
        assert hold.amount_usd == Decimal("0.030000") and hold.actual_usd is None
        assert (intent is not None) == (failure == "none")


async def test_actual_native_parent_quota_is_immutable(
    native_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    store, data = await native_plan(native_factory, tmp_path)
    await _approve(store, data)
    bound = data.children[0].binding
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=bound.actor_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
    )
    with pytest.raises(DBAPIError, match="Execution registration is immutable"):
        async with native_factory() as session, session.begin():
            await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
            parent = await session.get(ExecutionWork, (COMPANY, data.procedure.binding.task_id))
            assert parent is not None
            parent.model_requests_limit = 1
    runtime = ExecutionStore(native_factory, management_catalog=store.catalog)
    await runtime.claim(scope, identity(bound.actor_id), uuid4())
    assert (await runtime.get(scope, identity(bound.actor_id))).counters.model_requests == 0


async def test_native_guard_reads_genuine_positive_parent_without_rewriting_it(
    native_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    # Keep this >50-line public fixture together. No managed plan is approved or process issued.
    store, data = await native_plan(native_factory, tmp_path)
    child = data.children[0]
    parent = data.procedure.binding
    parent_item = WorkItem(
        company_id=COMPANY,
        task_id=parent.task_id,
        trace_id=parent.trace_id,
        goal_id=data.goal.goal_id,
        department="management",
        title="Synthetic positive ancestor",
        acceptance=("fixture.only",),
        budget_usd=data.procedure.allocation_usd,
    )
    directory, runtime = PersistentCompanyDirectory(native_factory), ExecutionStore(native_factory)
    for binding, item, quota, parent_id in (
        (parent, parent_item, AttemptQuota(model_requests=1), None),
        (child.binding, data.plan.items[0], child.quota, parent.task_id),
    ):
        await directory.register_work(
            WorkRegistration(
                company_id=COMPANY,
                workspace_id=binding.workspace_id,
                actor_id=binding.actor_id,
                task_id=binding.task_id,
                trace_id=binding.trace_id,
                parent_task_id=parent_id,
                allocation_usd=item.budget_usd,
                allowed_principals=(binding.actor_id,),
            ),
            control(),
        )
        scope = LedgerScope(
            company_id=COMPANY,
            principal_id=binding.actor_id,
            task_id=binding.task_id,
            trace_id=binding.trace_id,
        )
        await runtime.register(
            registration(binding, item, quota), scope, identity(binding.actor_id)
        )
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=child.binding.actor_id,
        task_id=child.binding.task_id,
        trace_id=child.binding.trace_id,
    )
    async with runtime_transaction(native_factory, scope, identity(child.binding.actor_id)) as (
        session,
        _,
        _,
    ):
        actual = await session.get(ExecutionWork, (COMPANY, child.binding.task_id))
        assert actual is not None
        with pytest.raises(ValueError, match="ancestor model allowance"):
            await require_native_ancestry(session, actual, store.catalog, child)


async def test_native_final_preparation_rejects_source_grant_expiry(
    native_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    store, data = await native_plan(native_factory, tmp_path)
    await _approve(store, data)
    bound = data.children[0].binding
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=bound.actor_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
    )
    lease = await ExecutionStore(native_factory, management_catalog=store.catalog).claim(
        scope, identity(bound.actor_id), uuid4()
    )
    action = await authorized_action(native_factory, bound, tool="company.builder.run.v1")
    await ResourceAccessStore(native_factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=bound.actor_id,
            active=True,
            expected_generation=2,
            expires_at=datetime.now(UTC) + timedelta(seconds=0.2),
        ),
    )

    class Delay:
        async def validate(
            self,
            session: AsyncSession,
            control: CompanyControl,
            work: ExecutionWork,
            action: JournalAction,
            now: datetime,
        ) -> None:
            await session.execute(select(func.pg_sleep(0.35)))

    with pytest.raises(ValueError):
        await EffectStore(native_factory, management_catalog=store.catalog).begin(
            lease, identity(bound.actor_id), action.action_id, before_intent=Delay()
        )
