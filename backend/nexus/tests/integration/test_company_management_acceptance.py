"""Actual restricted-PG protected acceptance; no model/SDK/business quality claim."""

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.event_models import BrainEvent
from nexus.company.management.acceptance_models import (
    ManagementAcceptanceProof,
    ManagementWorkAcceptance,
)
from nexus.company.management.acceptance_persistence import acceptance_record
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CostHold
from nexus.tests.integration.management_acceptance_fixture import (
    acceptance_factory as acceptance_factory,
)
from nexus.tests.integration.management_acceptance_fixture import (
    configured_acceptance,
    issue_accepted_report_fixture,
)
from nexus.tests.integration.management_acceptance_report_fixture import bindings
from nexus.tests.integration.test_company_directory import COMPANY
from nexus.tests.integration.test_company_execution_store import identity


async def saved_m1(factory: async_sessionmaker[AsyncSession]) -> tuple[object, ...]:
    async with factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        work = (await session.scalars(select(ExecutionWork).order_by(ExecutionWork.task_id))).all()
        effects = (
            await session.scalars(select(EffectIntent).order_by(EffectIntent.action_id))
        ).all()
        cost = (await session.scalars(select(CostHold).order_by(CostHold.action_id))).all()
        return (
            tuple(
                (row.task_id, row.state, row.fence, row.tool_attempts_used, row.model_requests_used)
                for row in work
            ),
            tuple(
                (row.action_id, row.state, row.receipt_json, row.verification_json)
                for row in effects
            ),
            tuple((row.action_id, row.state, row.amount_usd, row.actual_usd) for row in cost),
        )


async def test_actual_protected_check_publishes_once_without_m1_completion(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_acceptance(acceptance_factory, tmp_path)
    _, author, verifier = bindings(scenario.payload)
    before = await saved_m1(acceptance_factory)
    record = await scenario.store.publish_verified_result(
        scenario.verifier_lease,
        identity(verifier.actor_id),
        action_id=scenario.action_id,
        protected_result=scenario.protected_result,
    )
    assert record.verdict == "pass" and record.target.author == author
    replay = await scenario.store.publish_verified_result(
        scenario.verifier_lease,
        identity(verifier.actor_id),
        action_id=scenario.action_id,
        protected_result=scenario.protected_result,
    )
    assert record == replay and await saved_m1(acceptance_factory) == before
    async with acceptance_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.scalar(select(func.count()).select_from(ManagementWorkAcceptance)) == 1
        assert (
            await session.scalar(select(func.count()).select_from(ManagementAcceptanceProof)) == 1
        )
        event = await session.scalar(
            select(BrainEvent).where(
                BrainEvent.deduplication_key == f"management.acceptance:{record.acceptance_id}"
            )
        )
        assert (
            event is not None
            and event.kind == "verification_recorded"
            and event.action_id == scenario.action_id
        )
        row = await session.get(ManagementWorkAcceptance, (COMPANY, record.acceptance_id))
        assert row is not None and acceptance_record(row) == record


async def test_unknown_bill_yields_independent_rejection_and_preserves_hold(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_acceptance(acceptance_factory, tmp_path, actual_usd=None)
    _, _, verifier = bindings(scenario.payload)
    before = await saved_m1(acceptance_factory)
    result = await scenario.store.publish_verified_result(
        scenario.verifier_lease,
        identity(verifier.actor_id),
        action_id=scenario.action_id,
        protected_result=scenario.protected_result,
    )
    assert result.verdict == "reject" and await saved_m1(acceptance_factory) == before


async def test_registered_no_ttl_policy_accepts_current_immutable_result(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_acceptance(acceptance_factory, tmp_path, result_ttl=None)
    verifier = bindings(scenario.payload)[2]
    result = await scenario.store.publish_verified_result(
        scenario.verifier_lease,
        identity(verifier.actor_id),
        action_id=scenario.action_id,
        protected_result=scenario.protected_result,
    )
    assert result.verdict == "pass"


async def test_public_accepted_fixture_has_an_original_ordinary_dependent_child(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario, record = await issue_accepted_report_fixture(
        acceptance_factory, tmp_path, with_dependent=True
    )
    assert scenario.payload.plan.items[2].depends_on == (record.target.author.task_id,)
    assert record.verdict == "pass"


async def test_unsupported_semantic_assertion_remains_persisted_inconclusive(
    acceptance_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_acceptance(
        acceptance_factory, tmp_path, semantic_claim="Client Zeta is ready for an external launch"
    )
    verifier = bindings(scenario.payload)[2]
    result = await scenario.store.publish_verified_result(
        scenario.verifier_lease,
        identity(verifier.actor_id),
        action_id=scenario.action_id,
        protected_result=scenario.protected_result,
    )
    assert result.verdict == "inconclusive"
    async with acceptance_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        row = await session.get(ManagementWorkAcceptance, (COMPANY, result.acceptance_id))
        assert row is not None and row.verdict == "inconclusive"
