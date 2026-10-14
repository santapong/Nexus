"""Actual public scheduler atomically reserves and enqueues the approved pending verifier."""

from datetime import UTC, datetime

from sqlalchemy import func, select, text

from nexus.company.management.scheduling_contracts import (
    DueWake,
    ScanRequest,
    SchedulerPolicy,
    WorkflowRegistration,
)
from nexus.company.management.scheduling_store import ManagementScheduler
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.tests.engineering_pending_contracts import PendingEngineeringScenario
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_scheduler_support import FixtureIdentities, FixtureResources


async def enqueue_pending_verifier(item: PendingEngineeringScenario) -> SegmentCommand:
    """No worker launches; exact authorized native action and queue input commit in one scan."""
    job = item.verifier_spec.job
    async with item.runner.factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        assert await session.get(SegmentDispatch, (COMPANY, job.action_id)) is None
    scheduler = ManagementScheduler(
        item.runner.factory,
        SchedulerServices(
            policy=SchedulerPolicy(
                recipe_version="engineering-process-fixture-v1",
                max_tasks=1,
                workflows=(
                    WorkflowRegistration(
                        workflow_name="engineering.verify",
                        workflow_version="v1",
                        queue_name="nexus.engineering.native",
                        application_name="nexus-native-engineering",
                    ),
                ),
            ),
            catalog=item.catalog,
            artifacts=item.artifacts,
            freshness=item.freshness,
            identities=FixtureIdentities(),
            resources=FixtureResources(),
        ),
    )
    result = await scheduler.scan(
        control(),
        identity(OWNER),
        ScanRequest(
            company_id=COMPANY,
            wake=DueWake(bucket=datetime.now(UTC).replace(second=0, microsecond=0)),
            task_ids=(job.task_id,),
        ),
    )
    queued = result.receipt.work[0]
    assert queued.dispatch == "enqueued" and queued.action_id == job.action_id
    return await stored_enqueued_command(item, queued.workflow_id)


async def stored_enqueued_command(
    item: PendingEngineeringScenario, workflow_id: str | None
) -> SegmentCommand:
    """Read the actual stored native command and exact DBOS registered ABI after enqueue."""
    job = item.verifier_spec.job
    async with item.runner.factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        dispatch = await session.get(SegmentDispatch, (COMPANY, job.action_id))
        assert dispatch is not None
        command = SegmentCommand.model_validate_json(dispatch.binding_json)
        assert command.workflow_id == workflow_id
        status = (
            await session.execute(
                text(
                    "SELECT name,queue_name,application_name,application_version "
                    "FROM dbos.workflow_status WHERE workflow_uuid=:workflow"
                ),
                {"workflow": command.workflow_id},
            )
        ).one()
        assert tuple(status) == (
            "engineering.verify",
            "nexus.engineering.native",
            "nexus-native-engineering",
            "v1",
        )
    return command
