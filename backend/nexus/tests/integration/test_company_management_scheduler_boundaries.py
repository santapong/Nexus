"""Meaningful paged/expiry/authority boundaries on the exclusive normal010 scheduler DB."""

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import VerifiedIdentity
from nexus.company.management.control_store import ManagementControlStore
from nexus.company.management.scheduling_contracts import (
    EventWake,
    ScanRequest,
    WorkflowRegistration,
)
from nexus.company.management.scheduling_models import ManagementSchedulerScan
from nexus.company.management.transactions import ManagementDeniedError
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_contracts import ExecutionDeniedError
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import ActionRecord, LedgerScope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER
from nexus.tests.management_control_support import mandate
from nexus.tests.management_scheduler_support import (
    SchedulerDatabase,
    authorized_action,
    control,
    due_request,
    identity,
    setup_scheduler,
)
from nexus.tests.management_scheduler_support import scheduler_database as scheduler_database


async def test_final_authority_expiry_after_actual_dbos_sql_rolls_back_entire_scan(
    scheduler_database: SchedulerDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus.company.management import scheduling_queue

    scheduler, payload = await setup_scheduler(scheduler_database, tmp_path)
    approve = CompanyJournal.approve_registered

    async def nearly_expired(
        journal: CompanyJournal,
        scope: LedgerScope,
        action_id: UUID,
        digest: str,
        now: datetime,
        *,
        identity: VerifiedIdentity,
        approved: bool = True,
    ) -> ActionRecord:
        async with scheduler_database.app() as session:
            actual_now = await session.scalar(select(func.clock_timestamp()))
        assert isinstance(actual_now, datetime)
        return await approve(
            journal,
            scope,
            action_id,
            digest,
            actual_now - timedelta(hours=24) + timedelta(seconds=1),
            identity=identity,
            approved=approved,
        )

    monkeypatch.setattr(CompanyJournal, "approve_registered", nearly_expired)
    await authorized_action(scheduler_database.app, payload.children[0].binding)
    enqueue = scheduling_queue._enqueue_exact

    async def delayed_enqueue(
        session: AsyncSession, command: SegmentCommand, registration: WorkflowRegistration
    ) -> None:
        await enqueue(session, command, registration)
        await session.execute(select(func.pg_sleep(1.3)))

    monkeypatch.setattr(scheduling_queue, "_enqueue_exact", delayed_enqueue)
    with pytest.raises((ManagementDeniedError, ExecutionDeniedError)):
        await scheduler.scan(control(), identity(OWNER), await due_request(scheduler_database))
    async with scheduler_database.admin() as session:
        assert await session.scalar(text("SELECT count(*) FROM dbos.workflow_status")) == 0
        assert await session.scalar(select(func.count()).select_from(SegmentDispatch)) == 0
        assert await session.scalar(select(func.count()).select_from(ManagementSchedulerScan)) == 0


async def test_paginated_event_only_acknowledges_final_stable_native_page(
    scheduler_database: SchedulerDatabase,
    tmp_path: Path,
) -> None:
    scheduler, _ = await setup_scheduler(scheduler_database, tmp_path, max_tasks=1)
    from nexus.company.management.control_models import ManagementControlEvent

    async with scheduler_database.admin() as session:
        event = await session.scalar(
            select(ManagementControlEvent)
            .where(ManagementControlEvent.company_id == COMPANY)
            .order_by(ManagementControlEvent.sequence.desc())
        )
    assert event is not None
    request = ScanRequest(
        company_id=COMPANY, wake=EventWake(stream="control", event_id=event.event_id)
    )
    first = await scheduler.scan(control(), identity(OWNER), request)
    assert first.receipt.next_page is not None
    from nexus.company.brain.event_models import BrainEventCursor
    from nexus.company.management.scheduling_cursors import CONTROL_CONSUMER

    async with scheduler_database.admin() as session:
        cursor = await session.get(
            BrainEventCursor, (COMPANY, CONTROL_CONSUMER, scheduler.policy.recipe_version)
        )
        assert cursor is not None and cursor.last_sequence == 0
    second = await scheduler.scan(
        control(), identity(OWNER), request.model_copy(update={"page": first.receipt.next_page})
    )
    assert second.receipt.next_page is None
    assert (
        len(
            {
                row.eligibility.work.task_id
                for receipt in (first.receipt, second.receipt)
                for row in receipt.work
            }
        )
        == 2
    )
    async with scheduler_database.admin() as session:
        cursor = await session.get(
            BrainEventCursor, (COMPANY, CONTROL_CONSUMER, scheduler.policy.recipe_version)
        )
        assert cursor is not None and cursor.last_sequence == event.sequence


async def test_changed_control_range_does_not_silently_acknowledge_old_page(
    scheduler_database: SchedulerDatabase,
    tmp_path: Path,
) -> None:
    scheduler, payload = await setup_scheduler(scheduler_database, tmp_path, max_tasks=1)
    request = await due_request(scheduler_database)
    first = await scheduler.scan(control(), identity(OWNER), request)
    assert first.receipt.next_page is not None
    await ManagementControlStore(scheduler_database.app).publish_mandate(
        control(), identity(OWNER), mandate("v2"), expected_revision_id=payload.mandate.revision_id
    )
    with pytest.raises(ManagementDeniedError, match="page range"):
        await scheduler.scan(
            control(), identity(OWNER), request.model_copy(update={"page": first.receipt.next_page})
        )
