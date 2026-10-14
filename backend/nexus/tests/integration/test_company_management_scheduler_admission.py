"""Real current ACL, exact queue ABI and released owner-wait continuation boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from nexus.company.brain.access import ResourceAccessStore
from nexus.company.brain.access_contracts import ResourceAccessChange
from nexus.company.brain.access_models import BrainResource
from nexus.company.management.scheduling_contracts import WorkflowRegistration
from nexus.company.management.scheduling_models import ManagementSchedulerScan
from nexus.company.management.scheduling_queue import _enqueue_exact
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_store import ExecutionStore, next_segment_id
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import ACTOR, COMPANY, OWNER
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.management_scheduler_support import (
    APPLICATION,
    QUEUE,
    VERSION,
    WORKFLOW,
    SchedulerDatabase,
    authorized_action,
    control,
    due_request,
    identity,
    setup_scheduler,
)
from nexus.tests.management_scheduler_support import scheduler_database as scheduler_database


async def test_current_actor_source_revocation_blocks_prepared_action_without_cost_rewrite(
    scheduler_database: SchedulerDatabase,
    tmp_path: Path,
) -> None:
    scheduler, payload = await setup_scheduler(scheduler_database, tmp_path)
    await authorized_action(scheduler_database.app, payload.children[0].binding)
    resource = scheduler.services.catalog.resources[0].resource
    async with scheduler_database.admin() as session:
        native = await session.get(BrainResource, (COMPANY, resource.resource_id))
        assert native is not None
        generation = native.acl_generation
    await ResourceAccessStore(scheduler_database.app).change(
        owner_scope(),
        identity(OWNER),
        ResourceAccessChange(
            company_id=COMPANY,
            resource=resource,
            principal_id=ACTOR,
            active=False,
            expected_generation=generation,
        ),
    )
    before = await saved_m1(scheduler_database.app)
    scan = await scheduler.scan(control(), identity(OWNER), await due_request(scheduler_database))
    author = next(row for row in scan.receipt.work if row.eligibility.work.actor_id == ACTOR)
    assert author.eligibility.reason == "source_unavailable" and author.dispatch == "none"
    assert await saved_m1(scheduler_database.app) == before
    async with scheduler_database.admin() as session:
        assert await session.scalar(text("SELECT count(*) FROM dbos.workflow_status")) == 0


async def test_existing_sdk_id_with_wrong_abi_cannot_count_as_an_enqueued_dispatch(
    scheduler_database: SchedulerDatabase,
    tmp_path: Path,
) -> None:
    scheduler, payload = await setup_scheduler(scheduler_database, tmp_path)
    author = payload.children[0].binding
    action = await authorized_action(scheduler_database.app, author)
    command = SegmentCommand(
        company_id=COMPANY,
        task_id=author.task_id,
        trace_id=author.trace_id,
        actor_id=author.actor_id,
        workspace_id=author.workspace_id,
        run_id=author.run_id,
        action_id=action.action_id,
        segment_id=next_segment_id(
            await ExecutionStore(scheduler_database.app).get(
                LedgerScope(
                    company_id=COMPANY,
                    principal_id=author.actor_id,
                    task_id=author.task_id,
                    trace_id=author.trace_id,
                ),
                identity(author.actor_id),
            )
        ),
    )
    async with scheduler_database.admin() as session, session.begin():
        await _enqueue_exact(
            session,
            command,
            WorkflowRegistration(
                workflow_name=WORKFLOW,
                workflow_version="incompatible",
                queue_name=QUEUE,
                application_name=APPLICATION,
            ),
        )
    before = await saved_m1(scheduler_database.app)
    with pytest.raises(ManagementDeniedError, match="ABI differs"):
        await scheduler.scan(control(), identity(OWNER), await due_request(scheduler_database))
    assert await saved_m1(scheduler_database.app) == before
    async with scheduler_database.admin() as session:
        assert await session.scalar(select(func.count()).select_from(SegmentDispatch)) == 0
        assert await session.scalar(select(func.count()).select_from(ManagementSchedulerScan)) == 0


async def test_owner_wait_releases_capacity_then_scheduler_enqueues_same_run_next_segment(
    scheduler_database: SchedulerDatabase,
    tmp_path: Path,
) -> None:
    scheduler, payload = await setup_scheduler(scheduler_database, tmp_path)
    author = payload.children[0].binding
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=author.actor_id,
        task_id=author.task_id,
        trace_id=author.trace_id,
    )
    runtime = ExecutionStore(
        scheduler_database.app,
        management_catalog=scheduler.services.catalog,
        management_artifacts=scheduler.services.artifacts,
        management_freshness=scheduler.services.freshness,
    )
    lease = await runtime.claim(scope, identity(author.actor_id), uuid4())
    from nexus.company.contracts.actions import ActionProposal

    pending = ActionProposal(
        company_id=COMPANY,
        action_id=uuid4(),
        task_id=author.task_id,
        trace_id=author.trace_id,
        actor_id=author.actor_id,
        revision=1,
        tool="fake.internal.read.v1",
        tool_version=VERSION,
        resource="company.report",
        parameters={"operation": "read"},
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd="0.030000",
    )
    journal = CompanyJournal(scheduler_database.app)
    await journal.submit(pending, scope)
    waiting = await runtime.await_approval(lease, identity(author.actor_id), pending.action_id)
    assert waiting.worker_id is None and waiting.segment_number == 1
    first = await scheduler.scan(
        control(),
        identity(OWNER),
        await due_request(scheduler_database, task_ids=(author.task_id,)),
    )
    assert first.receipt.work[0].eligibility.reason == "approval_pending"
    await journal.approve_registered(
        scope.model_copy(update={"principal_id": OWNER}),
        pending.action_id,
        action_hash(pending),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        scope, pending.action_id, datetime.now(UTC), (), identity=identity(author.actor_id)
    )
    before = await saved_m1(scheduler_database.app)
    resumed = await scheduler.scan(
        control(), identity(OWNER), await due_request(scheduler_database)
    )
    queued = next(row for row in resumed.receipt.work if row.dispatch == "enqueued")
    assert queued.eligibility.work.run_id == author.run_id
    assert queued.segment_id == next_segment_id(waiting) and queued.segment_id != lease.segment_id
    assert await saved_m1(scheduler_database.app) == before
