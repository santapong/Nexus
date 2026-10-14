"""Historical acceptance and permanent cancellation retain actual billing/receipt facts."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.cancellation_contracts import CancellationCommand
from nexus.company.management.cancellation_store import WorkCancellationStore
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.tests.integration.management_acceptance_fixture import issue_accepted_report_fixture
from nexus.tests.integration.operating_report_fixture import configured_report
from nexus.tests.integration.operating_report_history_fixture import new_output_pair
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_operating_reports import (
    reports_factory as reports_factory,
)


async def test_cross_native_plan_current_acceptance_and_invalidated_history_are_distinct(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario, acceptance = await issue_accepted_report_fixture(reports_factory, tmp_path)
    data = new_output_pair(scenario.payload)
    proposal = await scenario.plans.propose(
        control(), identity(OWNER), data, expected_current_revision_id=None
    )
    await scenario.plans.approve_and_register(
        control(),
        identity(OWNER),
        proposal.plan_revision_id,
        proposal.sha256,
        expected_current_revision_id=proposal.plan_revision_id,
    )
    store = OperatingReportStore(
        reports_factory, scenario.plans.catalog, scenario.artifacts, scenario.freshness
    )
    selected = scenario.payload.children[0].binding
    now = datetime.now(UTC)
    saved = await store.save_snapshot(
        control(),
        identity(OWNER),
        proposal.plan_revision_id,
        data.children[2].binding.task_id,
        (selected.task_id,),
        period_start=now - timedelta(days=1),
        period_end=now,
    )
    assert saved.projection.accepted_task_ids == (selected.task_id,)
    assert saved.projection.actual_total_usd == Decimal("0.025000")
    assert saved.data.work[0].acceptance.publication.acceptance == acceptance
    await scenario.store.invalidate(
        control(), identity(OWNER), acceptance.acceptance_id, "source_changed"
    )
    invalidated = await store.save_snapshot(
        control(),
        identity(OWNER),
        proposal.plan_revision_id,
        data.children[2].binding.task_id,
        (selected.task_id,),
        period_start=now - timedelta(days=1),
        period_end=now,
    )
    assert invalidated.projection.accepted_task_ids == ()
    publication = invalidated.data.work[0].acceptance.publication
    assert publication.invalidated and publication.acceptance == acceptance
    assert invalidated.projection.receipt_task_ids == (selected.task_id,)
    assert invalidated.projection.actual_total_usd == saved.projection.actual_total_usd
    assert await store.get_saved(control(), identity(OWNER), saved.report_id) == saved


async def test_actual_owner_cancellation_and_inactive_work_preserve_receipts_and_bills(
    reports_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    scenario = await configured_report(reports_factory, tmp_path, issue_selected=True)
    selected = scenario.payload.children[2].binding
    await PersistentCompanyDirectory(reports_factory).set_work_active(
        control(), task_id=selected.task_id, active=False
    )
    now = datetime.now(UTC)
    args = (
        control(),
        identity(OWNER),
        scenario.saved.selection.plan.plan_revision_id,
        scenario.saved.selection.author.task_id,
        (selected.task_id,),
    )
    inactive = await scenario.store.save_snapshot(
        *args, period_start=now - timedelta(days=1), period_end=now
    )
    assert not inactive.data.work[0].registered_active
    assert inactive.projection.cancelled_task_ids == ()
    await WorkCancellationStore(reports_factory).cancel(
        control(),
        identity(OWNER),
        CancellationCommand(
            company_id=selected.company_id, target=selected, reason="owner_stopped"
        ),
    )
    cancelled = await scenario.store.save_snapshot(
        *args, period_start=now - timedelta(days=1), period_end=now
    )
    assert cancelled.projection.cancelled_task_ids == (selected.task_id,)
    assert not cancelled.data.work[0].registered_active
    assert cancelled.projection.receipt_task_ids == (selected.task_id,)
    assert cancelled.projection.actual_total_usd == Decimal("0.015000")
    assert cancelled.data.work[0].receipt == inactive.data.work[0].receipt
