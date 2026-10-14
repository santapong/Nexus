"""Actual native pending→owner decision→DBOS dispatch→receipt→independent acceptance loop."""

from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.native_loop_config import (
    load_native_operating_registration,
    save_native_operating_registration,
)
from nexus.company.management.native_loop_store import NativeReportOperatingLoop
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.native_report_worker import execute_native_report
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CostHold, JournalAction
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.operating_loop_support import configured_loop, decide_existing
from nexus.tests.operating_loop_support import loop_factory as loop_factory


async def queued_command(
    factory: async_sessionmaker[AsyncSession], workflow_id: str
) -> SegmentCommand:
    async with factory() as session:
        raw = await session.scalar(
            text("SELECT inputs FROM dbos.workflow_input WHERE workflow_uuid=:id"),
            {"id": workflow_id},
        )
    import json

    assert isinstance(raw, str)
    return SegmentCommand.model_validate_json(json.loads(raw)["positionalArgs"][0])


async def test_registered_loop_runs_exact_author_and_verifier_then_idles_without_new_work(
    loop_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    loop, case = await configured_loop(loop_factory, tmp_path / "blobs")
    path = tmp_path / "server-registration.json"
    await save_native_operating_registration(path, loop.registration)
    loop = NativeReportOperatingLoop(
        await load_native_operating_registration(path), case.preparation, case.native
    )
    baseline = await saved_m1(loop_factory)
    first = await loop.tick(control(), identity(OWNER))
    assert first.state == "author_pending" and first.pending and first.preparation_performed
    assert await saved_m1(loop_factory) == baseline
    waiting = await loop.tick(control(), identity(OWNER))
    assert waiting.state == "author_pending" and not waiting.preparation_performed
    assert await saved_m1(loop_factory) == baseline
    await decide_existing(loop_factory, first.pending)
    author = await loop.tick(control(), identity(OWNER))
    assert author.state == "author_dispatched" and author.scheduled and author.scheduled.workflow_id
    command = await queued_command(loop_factory, author.scheduled.workflow_id)
    result = await execute_native_report(case.native, command, workflow_id=command.workflow_id)
    assert result.status == "published" and result.receipt_id
    before_check = await saved_m1(loop_factory)
    check = await loop.tick(control(), identity(OWNER))
    assert check.state == "verifier_pending" and check.pending and check.preparation_performed
    async with loop_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        verifier = await session.get(
            ExecutionWork, (COMPANY, case.payload.children[1].binding.task_id)
        )
        assert verifier and verifier.worker_id is None and verifier.lease_until is None
        assert (
            verifier.state == "awaiting_approval"
            and verifier.tool_attempts_used == 0
            and verifier.model_requests_used == 0
        )
    pending_state = await saved_m1(loop_factory)
    assert await loop.tick(control(), identity(OWNER))
    assert await saved_m1(loop_factory) == pending_state
    await decide_existing(loop_factory, check.pending)
    verifying = await loop.tick(control(), identity(OWNER))
    assert (
        verifying.state == "verifier_dispatched"
        and verifying.scheduled
        and verifying.scheduled.workflow_id
    )
    command = await queued_command(loop_factory, verifying.scheduled.workflow_id)
    result = await execute_native_report(case.native, command, workflow_id=command.workflow_id)
    assert result.status == "accepted" and result.acceptance_id
    completed = await saved_m1(loop_factory)
    assert completed != before_check
    for _ in range(2):
        idle = await loop.tick(control(), identity(OWNER))
        assert (
            idle.state == "accepted"
            and idle.acceptance
            and idle.acceptance.acceptance_id == result.acceptance_id
        )
        assert (
            idle.model_requests == 0
            and not idle.preparation_performed
            and idle.pending is None
            and idle.scheduled is None
        )
        assert await saved_m1(loop_factory) == completed
    async with loop_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        for model in (JournalAction, EffectIntent, CostHold):
            assert await session.scalar(select(func.count()).select_from(model)) == 2
