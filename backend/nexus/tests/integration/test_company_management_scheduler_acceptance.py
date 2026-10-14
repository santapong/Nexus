"""Native independent acceptance/explicit invalidation and lifetime quota are scheduler inputs."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select, text

from nexus.company.management.scheduling_store import ManagementScheduler
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.harness.journal_models import CostHold
from nexus.tests.integration.management_acceptance_fixture import issue_accepted_report_fixture
from nexus.tests.integration.test_company_directory import OWNER
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.management_scheduler_support import (
    FixtureIdentities,
    FixtureResources,
    SchedulerDatabase,
    authorized_action,
    control,
    due_request,
    identity,
    setup_scheduler,
)
from nexus.tests.management_scheduler_support import scheduler_database as scheduler_database


async def test_actual_pass_unlocks_dependency_and_invalidation_restores_waiting(
    scheduler_database: SchedulerDatabase,
    tmp_path: Path,
) -> None:
    scenario, accepted = await issue_accepted_report_fixture(
        scheduler_database.app, tmp_path, with_dependent=True
    )
    # Keep public native fixture authority; only reuse constructor configuration from setup.
    from nexus.company.management.scheduling_contracts import SchedulerPolicy, WorkflowRegistration
    from nexus.tests.management_scheduler_support import APPLICATION, QUEUE, VERSION, WORKFLOW

    scheduler = ManagementScheduler(
        scheduler_database.app,
        SchedulerServices(
            policy=SchedulerPolicy(
                recipe_version="management.scheduler.offline.v1",
                workflows=(
                    WorkflowRegistration(
                        workflow_name=WORKFLOW,
                        workflow_version=VERSION,
                        queue_name=QUEUE,
                        application_name=APPLICATION,
                    ),
                ),
            ),
            catalog=scenario.plans.catalog,
            artifacts=scenario.artifacts,
            freshness=scenario.freshness,
            identities=FixtureIdentities(),
            resources=FixtureResources(),
        ),
    )
    dependent = scenario.payload.children[2].binding
    action = await authorized_action(scheduler_database.app, dependent)
    before = await saved_m1(scheduler_database.app)
    first = await scheduler.scan(control(), identity(OWNER), await due_request(scheduler_database))
    author = next(
        row
        for row in first.receipt.work
        if row.eligibility.work.task_id == accepted.target.author.task_id
    )
    issued = next(
        row for row in first.receipt.work if row.eligibility.work.task_id == dependent.task_id
    )
    assert author.eligibility.reason == "already_accepted" and author.dispatch == "none"
    assert issued.dispatch == "enqueued" and issued.action_id == action.action_id
    assert await saved_m1(scheduler_database.app) == before
    await scenario.store.invalidate(
        control(), identity(OWNER), accepted.acceptance_id, "source_changed"
    )
    after = await saved_m1(scheduler_database.app)
    changed = await scheduler.scan(
        control(),
        identity(OWNER),
        await due_request(scheduler_database, task_ids=(dependent.task_id,)),
    )
    assert changed.receipt.work[0].eligibility.reason == "dependency_unaccepted"
    assert changed.receipt.work[0].dispatch == "none" and changed.receipt.model_requests == 0
    assert await saved_m1(scheduler_database.app) == after
    async with scheduler_database.admin() as session:
        assert await session.scalar(select(func.count()).select_from(SegmentDispatch)) == 1
        assert await session.scalar(text("SELECT count(*) FROM dbos.workflow_status")) == 1


async def test_zero_native_tool_slice_waits_without_resetting_action_reservation(
    scheduler_database: SchedulerDatabase,
    tmp_path: Path,
) -> None:
    scheduler, payload = await setup_scheduler(scheduler_database, tmp_path, tool_attempts=0)
    action = await authorized_action(scheduler_database.app, payload.children[0].binding)
    before = await saved_m1(scheduler_database.app)
    scan = await scheduler.scan(control(), identity(OWNER), await due_request(scheduler_database))
    author = next(
        row for row in scan.receipt.work if row.eligibility.work.task_id == action.task_id
    )
    assert author.eligibility.reason == "budget_exhausted" and author.dispatch == "none"
    assert await saved_m1(scheduler_database.app) == before
    async with scheduler_database.admin() as session:
        hold = await session.get(CostHold, action.action_id)
        assert hold is not None and hold.state == "held" and hold.actual_usd is None
        assert await session.scalar(text("SELECT count(*) FROM dbos.workflow_status")) == 0
