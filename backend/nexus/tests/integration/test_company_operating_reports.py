"""Native owner reporting uses its own disposable DB and public approved work path."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.scope_support import BrainDeniedError, brain_transaction
from nexus.company.management.acceptance_errors import AcceptanceDeniedError
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.report_checker import check_internal_report
from nexus.settings import settings
from nexus.tests.integration.management_acceptance_fixture import configured_acceptance
from nexus.tests.integration.operating_report_fixture import configured_report, loaded_report
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import OWNER, control, migrate
from nexus.tests.integration.test_company_execution_store import identity


@pytest.fixture
async def reports_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_management_reports"
    admin, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
    migrated = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        migrated = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if migrated:
            async with admin.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


async def test_native_owner_snapshot_captures_original_selection_and_lifetime_basis(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_acceptance(reports_factory, tmp_path, with_dependent=True)
    store = OperatingReportStore(
        reports_factory, scenario.plans.catalog, scenario.artifacts, scenario.freshness
    )
    current = scenario.payload.children[0].binding

    async with brain_transaction(reports_factory, owner_scope(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        binding = await ManagementPlanStore.current_binding(
            session, current.company_id, current.task_id
        )
        assert binding is not None
        revision = binding.plan.plan_revision_id
    observed = datetime.now(UTC)
    saved = await store.save_snapshot(
        control(),
        identity(OWNER),
        revision,
        current.task_id,
        (scenario.payload.children[2].binding.task_id,),
        period_start=observed - timedelta(days=1),
        period_end=observed,
    )
    assert saved.ledger_basis == "selected_work_lifetime"
    assert saved.projection.snapshot.work[0].execution_state == "eligible"
    assert saved.projection.actual_total_usd == 0 and saved.projection.accepted_task_ids == ()


async def test_actual_protected_output_loads_native_snapshot_without_owner_impersonation(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_report(reports_factory, tmp_path, issue_selected=True)
    command = await loaded_report(scenario)
    assert command.snapshot is not None
    assert command.snapshot.operating == scenario.saved.projection
    assert command.snapshot.observed_at == scenario.saved.observed_at
    assert check_internal_report(command).verdict == "pass"
    assert command.snapshot.operating.actual_total_usd == Decimal("0.015000")
    assert (
        await scenario.store.get_saved(control(), identity(OWNER), scenario.saved.report_id)
        == scenario.saved
    )


async def test_native_unknown_selected_bill_is_visible_and_never_zero(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_report(
        reports_factory, tmp_path, issue_selected=True, selected_bill=None
    )
    command = await loaded_report(scenario)
    assert command.snapshot is not None and command.snapshot.operating is not None
    projected = command.snapshot.operating
    assert projected.actual_total_usd is None
    assert projected.unknown_charge_ids == (scenario.selected_action_id,)
    assert projected.snapshot.ledger.spent_usd == 0
    assert check_internal_report(command).verdict == "pass"


async def test_saved_report_requires_actual_current_owner_identity(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_report(reports_factory, tmp_path)
    verifier = scenario.payload.children[1].binding
    with pytest.raises((BrainDeniedError, AcceptanceDeniedError)):
        await scenario.store.get_saved(
            control(), identity(verifier.actor_id), scenario.saved.report_id
        )


async def test_root_and_child_selected_lifetime_charges_count_only_actual_leaf_once(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_report(reports_factory, tmp_path, issue_selected=True)
    root = scenario.payload.procedure.binding
    third = scenario.payload.children[2].binding
    saved = await scenario.store.save_snapshot(
        control(),
        identity(OWNER),
        scenario.saved.selection.plan.plan_revision_id,
        scenario.saved.selection.author.task_id,
        (root.task_id, third.task_id),
        period_start=scenario.saved.period_start,
        period_end=scenario.saved.period_end,
    )
    assert {row.work.task_id for row in saved.data.work} == {root.task_id, third.task_id}
    assert len(saved.data.charges) == 1
    assert saved.data.charges[0].root_task_id == root.task_id
    assert saved.projection.actual_total_usd == Decimal("0.015000")


@pytest.mark.parametrize("selection", ["duplicate", "output", "unknown"])
async def test_owner_selection_cannot_duplicate_output_or_invent_native_work(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    selection: str,
) -> None:
    from uuid import uuid4

    scenario = await configured_report(reports_factory, tmp_path)
    selected = scenario.payload.children[2].binding.task_id
    ids = (
        (selected, selected)
        if selection == "duplicate"
        else (scenario.saved.selection.author.task_id,)
        if selection == "output"
        else (uuid4(),)
    )
    with pytest.raises(ValueError):
        await scenario.store.save_snapshot(
            control(),
            identity(OWNER),
            scenario.saved.selection.plan.plan_revision_id,
            scenario.saved.selection.author.task_id,
            ids,
            period_start=scenario.saved.period_start,
            period_end=scenario.saved.period_end,
        )
