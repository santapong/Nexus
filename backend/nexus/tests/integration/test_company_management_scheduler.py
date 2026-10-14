"""Real restricted-PG scans/DBOS enqueue, current authority, rollback and two-scheduler safety."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.brain.event_models import BrainEventCursor
from nexus.company.management.scheduling_contracts import ScanReceipt
from nexus.company.management.scheduling_models import ManagementSchedulerScan
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_store import ExecutionStore
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CompanyControl, JournalAction
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.management_scheduler_support import (
    SchedulerDatabase,
    authorized_action,
    control,
    due_request,
    identity,
    setup_scheduler,
)
from nexus.tests.management_scheduler_support import scheduler_database as scheduler_database


async def test_idle_and_unbound_work_scans_spend_no_model_request_or_create_action(
    scheduler_database: SchedulerDatabase,
    tmp_path: Path,
) -> None:
    scheduler, _ = await setup_scheduler(scheduler_database, tmp_path)
    request = await due_request(scheduler_database)
    first = await scheduler.scan(control(), identity(OWNER), request)
    second = await scheduler.scan(
        control().model_copy(update={"operation_id": uuid4()}), identity(OWNER), request
    )
    assert second.replayed and second.receipt == first.receipt
    assert first.receipt.model_requests == 0
    assert {row.eligibility.reason for row in first.receipt.work} == {
        "approval_pending",
        "verification_unbound",
    }
    async with scheduler_database.admin() as session:
        assert await session.scalar(text("SELECT count(*) FROM dbos.workflow_status")) == 0
        assert await session.scalar(select(func.count()).select_from(SegmentDispatch)) == 0
        assert await session.scalar(select(func.count()).select_from(JournalAction)) == 0
        assert await session.scalar(select(func.count()).select_from(ManagementSchedulerScan)) == 1


async def test_two_schedulers_commit_one_native_dispatch_and_exact_dbos_workflow(
    scheduler_database: SchedulerDatabase,
    tmp_path: Path,
) -> None:
    scheduler, payload = await setup_scheduler(scheduler_database, tmp_path)
    author = payload.children[0].binding
    action = await authorized_action(scheduler_database.app, author)
    request = await due_request(scheduler_database)
    results = await asyncio.gather(
        *(
            scheduler.scan(
                control().model_copy(update={"operation_id": uuid4()}), identity(OWNER), request
            )
            for _ in range(2)
        )
    )
    assert sum(row.replayed for row in results) == 1
    assert results[0].receipt == results[1].receipt
    queued = [row for row in results[0].receipt.work if row.dispatch == "enqueued"]
    assert len(queued) == 1 and queued[0].action_id == action.action_id
    async with scheduler_database.admin() as session:
        assert await session.scalar(text("SELECT count(*) FROM dbos.workflow_status")) == 1
        assert await session.scalar(select(func.count()).select_from(SegmentDispatch)) == 1


async def test_enqueue_failure_rolls_back_dispatch_cursor_and_scan_receipt(
    scheduler_database: SchedulerDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.management import scheduling_store

    scheduler, payload = await setup_scheduler(scheduler_database, tmp_path)
    await authorized_action(scheduler_database.app, payload.children[0].binding)
    original = scheduling_store._save

    async def fail_after_actual_receipt_insert(session: AsyncSession, record: ScanReceipt) -> None:
        await original(session, record)
        raise RuntimeError("controlled scan receipt failure")

    monkeypatch.setattr(scheduling_store, "_save", fail_after_actual_receipt_insert)
    with pytest.raises(RuntimeError, match="controlled scan receipt failure"):
        await scheduler.scan(control(), identity(OWNER), await due_request(scheduler_database))
    async with scheduler_database.admin() as session:
        assert await session.scalar(select(func.count()).select_from(SegmentDispatch)) == 0
        assert await session.scalar(select(func.count()).select_from(BrainEventCursor)) == 0
        assert await session.scalar(select(func.count()).select_from(ManagementSchedulerScan)) == 0
        assert await session.scalar(text("SELECT count(*) FROM dbos.workflow_status")) == 0


async def test_live_lease_is_reported_without_takeover_or_new_enqueue(
    scheduler_database: SchedulerDatabase,
    tmp_path: Path,
) -> None:
    scheduler, payload = await setup_scheduler(scheduler_database, tmp_path)
    bound = payload.children[0].binding
    scope = LedgerScope(
        company_id=COMPANY,
        principal_id=bound.actor_id,
        task_id=bound.task_id,
        trace_id=bound.trace_id,
    )
    runtime = ExecutionStore(
        scheduler_database.app,
        management_catalog=scheduler.services.catalog,
        management_artifacts=scheduler.services.artifacts,
        management_freshness=scheduler.services.freshness,
    )
    lease = await runtime.claim(scope, identity(bound.actor_id), uuid4())
    scan = await scheduler.scan(control(), identity(OWNER), await due_request(scheduler_database))
    observed = next(
        row for row in scan.receipt.work if row.eligibility.work.task_id == bound.task_id
    )
    assert observed.eligibility.reason == "dispatch_active" and observed.dispatch == "none"
    assert (await runtime.get(scope, identity(bound.actor_id))).fence == lease.fence


async def test_paused_company_records_truthful_blocked_scan_without_new_dispatch(
    scheduler_database: SchedulerDatabase,
    tmp_path: Path,
) -> None:
    scheduler, _ = await setup_scheduler(scheduler_database, tmp_path)
    async with scheduler_database.app() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        current = await session.get(CompanyControl, COMPANY)
        assert current is not None
        current.paused = True
    result = await scheduler.scan(control(), identity(OWNER), await due_request(scheduler_database))
    assert all(row.eligibility.reason == "company_paused" for row in result.receipt.work)
    assert result.receipt.model_requests == 0
