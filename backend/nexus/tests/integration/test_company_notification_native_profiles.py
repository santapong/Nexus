"""Actual owner-only no-model notification admission, without drafts or transport."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange, ResourceRef
from nexus.company.contracts.work import WorkItem
from nexus.company.control_store import CompanyControls
from nexus.company.directory_contracts import WorkRegistration
from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.plan_registration import registration
from nexus.execution.native_profile_checks import require_notification_ancestry
from nexus.execution.runtime_contracts import AttemptQuota
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import runtime_transaction
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CostHold
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE, owner_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_native_profile_fixture import (
    TOOL,
    notification_action,
    notification_native_scenario,
)
from nexus.tests.notification_native_profile_fixture import (
    notification_native_factory as notification_native_factory,
)


async def test_native_owner_sender_empty_model_catalog_commits_only_one_intent(
    notification_native_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await notification_native_scenario(notification_native_factory, tmp_path)
    assert case.catalog.models.models == () and case.catalog.model_observations == ()

    lease = await case.runtime.claim(case.scope, identity(OWNER), uuid4())
    before = await case.runtime.get(case.scope, identity(OWNER))
    action = await notification_action(notification_native_factory, case)
    started = await case.effects.begin(lease, identity(OWNER), action.action_id)
    assert started.permit_external_call and started.record.attempt_kind == "tool_attempts"
    assert not (
        await case.effects.begin(lease, identity(OWNER), action.action_id)
    ).permit_external_call
    released = await case.runtime.release(lease, identity(OWNER))
    assert released.state == "outcome_unknown"
    assert released.registration == before.registration
    assert released.counters.model_requests == 0 and released.counters.tool_attempts == 1
    async with notification_native_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        parent = await session.get(ExecutionWork, (COMPANY, case.payload.procedure.binding.task_id))
        intent = await session.get(EffectIntent, (COMPANY, action.action_id))
        hold = await session.get(CostHold, action.action_id)
        assert parent is not None and intent is not None and hold is not None
        assert (
            parent.model_requests_limit,
            parent.model_requests_used,
            parent.model_requests_delegated,
        ) == (0, 0, 0)
        assert intent.state == "outcome_unknown" and intent.receipt_json is None
        assert (
            hold.state == "unknown"
            and hold.amount_usd == Decimal(".03")
            and hold.actual_usd is None
        )


async def test_actual_member_sender_registration_cannot_claim_owner_worker(
    notification_native_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await notification_native_scenario(notification_native_factory, tmp_path, actor=ACTOR)
    before = await case.runtime.get(case.scope, identity(ACTOR))
    with pytest.raises(
        ValueError, match="Current management execution evidence is unavailable"
    ) as denied:
        await case.runtime.claim(case.scope, identity(ACTOR), uuid4())
    assert denied.value.__cause__ is not None and "actual owner" in str(denied.value.__cause__)
    assert await case.runtime.get(case.scope, identity(ACTOR)) == before


@pytest.mark.parametrize(
    "failure", ["source", "pause", "charter", "wrong_tool", "model_kind", "missing_approval"]
)
async def test_native_sender_current_authority_denies_before_intent(
    notification_native_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    failure: str,
) -> None:
    case = await notification_native_scenario(notification_native_factory, tmp_path)
    lease = await case.runtime.claim(case.scope, identity(OWNER), uuid4())
    before = await case.runtime.get(case.scope, identity(OWNER))
    action = await notification_action(
        notification_native_factory,
        case,
        tool="model.request.v1" if failure == "wrong_tool" else TOOL,
        approve=failure != "missing_approval",
    )
    if failure == "source":
        await ResourceAccessStore(notification_native_factory).change(
            owner_scope(),
            identity(OWNER),
            ResourceAccessChange(
                company_id=COMPANY,
                resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
                principal_id=OWNER,
                active=False,
                expected_generation=1,
            ),
        )
    if failure == "pause":
        await CompanyControls(notification_native_factory).set_paused_registered(
            control(), identity(OWNER), True
        )
    if failure == "charter":
        await ManagementControlStore(notification_native_factory).revoke_charter(
            control(), identity(OWNER), case.payload.children[0].charter
        )
    with pytest.raises(ValueError):
        await case.effects.begin(
            lease,
            identity(OWNER),
            action.action_id,
            kind="model_requests" if failure == "model_kind" else "tool_attempts",
        )
    assert await case.runtime.get(case.scope, identity(OWNER)) == before
    async with notification_native_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.get(EffectIntent, (COMPANY, action.action_id)) is None
        hold = await session.get(CostHold, action.action_id)
        if failure == "missing_approval":
            assert hold is None
        else:
            assert (
                hold is not None and hold.actual_usd is None and hold.amount_usd == Decimal(".03")
            )


async def test_copied_metadata_and_genuine_positive_ancestor_do_not_admit_notification(
    notification_native_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    # Actual immutable positive parent is registered publicly; no managed plan is forged.
    case = await notification_native_scenario(notification_native_factory, tmp_path, register=False)
    child, parent = case.payload.children[0], case.payload.procedure.binding
    parent_item = WorkItem(
        company_id=COMPANY,
        task_id=parent.task_id,
        trace_id=parent.trace_id,
        goal_id=case.payload.goal.goal_id,
        department="management",
        title="Genuine positive model allowance fixture",
        acceptance=("fixture.only",),
        budget_usd=Decimal("1"),
    )
    directory = PersistentCompanyDirectory(notification_native_factory)
    for binding, item, quota, parent_id in (
        (
            parent,
            parent_item,
            AttemptQuota(model_requests=1, tool_attempts=1, rework_rounds=0, plan_revisions=1),
            None,
        ),
        (child.binding, case.payload.plan.items[0], child.quota, parent.task_id),
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
        await ExecutionStore(notification_native_factory).register(
            registration(binding, item, quota), scope, identity(binding.actor_id)
        )
    async with runtime_transaction(notification_native_factory, case.scope, identity(OWNER)) as (
        session,
        control_row,
        _,
    ):
        actual = await session.get(ExecutionWork, (COMPANY, child.binding.task_id))
        assert actual is not None
        with pytest.raises(ValueError, match="ancestor model allowance"):
            await require_notification_ancestry(session, control_row, actual, case.catalog, child)
        corrupted = child.model_copy(
            update={"quota": child.quota.model_copy(update={"model_requests": 1})}
        )
        with pytest.raises(ValueError):
            await require_notification_ancestry(
                session, control_row, actual, case.catalog, corrupted
            )


async def test_exact_owner_approval_hash_is_required_before_reservation(
    notification_native_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await notification_native_scenario(notification_native_factory, tmp_path)
    action = await notification_action(notification_native_factory, case, approve=False)
    with pytest.raises(ValueError):
        await CompanyJournal(notification_native_factory).approve_registered(
            case.scope, action.action_id, "a" * 64, datetime.now(UTC), identity=identity(OWNER)
        )
    lease = await case.runtime.claim(case.scope, identity(OWNER), uuid4())
    with pytest.raises(ValueError):
        await case.effects.begin(lease, identity(OWNER), action.action_id)
    async with notification_native_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.get(CostHold, action.action_id) is None
        assert await session.get(EffectIntent, (COMPANY, action.action_id)) is None


async def test_spent_native_tool_allowance_cannot_create_new_sender_intent(
    notification_native_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    case = await notification_native_scenario(notification_native_factory, tmp_path)
    lease = await case.runtime.claim(case.scope, identity(OWNER), uuid4())
    spent = await case.runtime.reserve_attempt(lease, identity(OWNER), "tool_attempts", uuid4())
    assert spent.counters.model_requests == 0 and spent.counters.tool_attempts == 1
    action = await notification_action(notification_native_factory, case)
    with pytest.raises(ValueError):
        await case.effects.begin(lease, identity(OWNER), action.action_id)
    assert await case.runtime.get(case.scope, identity(OWNER)) == spent
    async with notification_native_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.get(EffectIntent, (COMPANY, action.action_id)) is None
        hold = await session.get(CostHold, action.action_id)
        assert hold is not None and hold.amount_usd == Decimal(".03") and hold.actual_usd is None


async def test_native_source_grant_expiry_during_awaited_preparation_prevents_intent(
    notification_native_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    from datetime import timedelta

    from nexus.harness.journal_models import CompanyControl, JournalAction

    case = await notification_native_scenario(notification_native_factory, tmp_path)
    lease = await case.runtime.claim(case.scope, identity(OWNER), uuid4())
    action = await notification_action(notification_native_factory, case)
    before = await case.runtime.get(case.scope, identity(OWNER))
    async with notification_native_factory() as session:
        now = await session.scalar(select(func.clock_timestamp()))
    assert now is not None
    await ResourceAccessStore(notification_native_factory).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
            principal_id=OWNER,
            active=True,
            expected_generation=1,
            expires_at=now + timedelta(seconds=3),
        ),
    )

    class Delay:
        async def validate(
            self,
            session: AsyncSession,
            control_row: CompanyControl,
            work: ExecutionWork,
            proposal: JournalAction,
            checked: datetime,
        ) -> None:
            await session.execute(select(func.pg_sleep(3.3)))

    with pytest.raises(ValueError):
        await case.effects.begin(lease, identity(OWNER), action.action_id, before_intent=Delay())
    assert await case.runtime.get(case.scope, identity(OWNER)) == before
    async with notification_native_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.get(EffectIntent, (COMPANY, action.action_id)) is None
        hold = await session.get(CostHold, action.action_id)
        assert hold is not None and hold.amount_usd == Decimal(".03") and hold.actual_usd is None
