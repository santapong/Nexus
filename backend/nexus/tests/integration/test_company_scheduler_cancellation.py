"""Permanent explicit owner cancellation is projected separately from inactive work."""

from pathlib import Path

import pytest

from nexus.company.directory_store import PersistentCompanyDirectory
from nexus.company.management.cancellation_contracts import CancellationCommand
from nexus.company.management.cancellation_store import WorkCancellationStore
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_plan_support import authorized_action
from nexus.tests.management_scheduler_support import (
    SchedulerDatabase,
    due_request,
    setup_scheduler,
)
from nexus.tests.management_scheduler_support import (
    scheduler_database as scheduler_database,
)


@pytest.mark.parametrize("target", ["procedure", "child", "inactive"])
async def test_scheduler_preserves_distinct_explicit_stop_without_dispatch(
    scheduler_database: SchedulerDatabase, tmp_path: Path, target: str
) -> None:
    scheduler, plan = await setup_scheduler(scheduler_database, tmp_path)
    child = plan.children[0].binding
    await authorized_action(scheduler_database.app, child)
    if target == "inactive":
        await PersistentCompanyDirectory(scheduler_database.app).set_work_active(
            control(),
            task_id=child.task_id,
            active=False,
        )
    else:
        binding = plan.procedure.binding if target == "procedure" else child
        await WorkCancellationStore(scheduler_database.app).cancel(
            control(),
            identity(OWNER),
            CancellationCommand(
                company_id=COMPANY,
                target=binding,
                reason="Owner stops this supervised workflow",
            ),
        )
    result = await scheduler.scan(control(), identity(OWNER), await due_request(scheduler_database))
    selected = next(
        row for row in result.receipt.work if row.eligibility.work.task_id == child.task_id
    )
    assert selected.dispatch == "none"
    if target == "inactive":
        assert selected.eligibility.state == "blocked"
        assert selected.eligibility.reason != "work_cancelled"
    else:
        assert (selected.eligibility.state, selected.eligibility.reason) == (
            "cancelled",
            "work_cancelled",
        )
        if target == "procedure":
            assert all(row.eligibility.state == "cancelled" for row in result.receipt.work)
