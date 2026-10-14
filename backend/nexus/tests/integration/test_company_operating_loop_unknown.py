"""An actual issued intent without output remains unknown; ticks create no replacement effect."""

from dataclasses import replace
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.control_store import CompanyControls
from nexus.company.management.cancellation_contracts import CancellationCommand
from nexus.company.management.cancellation_store import WorkCancellationStore
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.native_report_services import NativePhase
from nexus.execution.native_report_worker import execute_native_report
from nexus.execution.runtime_models import EffectIntent
from nexus.harness.journal_models import CostHold, JournalAction
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_management_acceptance import saved_m1
from nexus.tests.integration.test_company_operating_loop import queued_command
from nexus.tests.operating_loop_support import configured_loop, decide_and_authorize
from nexus.tests.operating_loop_support import loop_factory as loop_factory


async def test_actual_issued_missing_output_idles_unknown_and_survives_pause_and_cancellation(
    loop_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    loop, case = await configured_loop(loop_factory, tmp_path)
    pending = await loop.tick(control(), identity(OWNER))
    assert pending.pending
    await decide_and_authorize(loop_factory, case, pending.pending)
    dispatch = await loop.tick(control(), identity(OWNER))
    assert dispatch.scheduled and dispatch.scheduled.workflow_id
    command = await queued_command(loop_factory, dispatch.scheduled.workflow_id)

    expected_command = command

    async def interrupt(phase: NativePhase, command: SegmentCommand) -> None:
        assert command == expected_command
        if phase == "intent_committed":
            raise RuntimeError("Intent issued; no native output was published")

    result = await execute_native_report(
        replace(case.native, hook=interrupt), command, workflow_id=command.workflow_id
    )
    assert result.status == "outcome_unknown" and result.receipt_id is None
    before = await saved_m1(loop_factory)
    for _ in range(2):
        unknown = await loop.tick(control(), identity(OWNER))
        assert unknown.state == "outcome_unknown" and unknown.model_requests == 0
        assert unknown.pending is None and unknown.scheduled is None
        assert await saved_m1(loop_factory) == before
    await CompanyControls(loop_factory).set_paused_registered(control(), identity(OWNER), True)
    assert (await loop.tick(control(), identity(OWNER))).state == "blocked"
    await WorkCancellationStore(loop_factory).cancel(
        control(),
        identity(OWNER),
        CancellationCommand(
            company_id=COMPANY,
            target=case.payload.children[0].binding,
            reason="Keep unknown issued charge; stop new work",
        ),
    )
    await CompanyControls(loop_factory).set_paused_registered(control(), identity(OWNER), False)
    assert (await loop.tick(control(), identity(OWNER))).reason == "work_cancelled"
    assert await saved_m1(loop_factory) == before
    async with loop_factory() as session, session.begin():
        await session.execute(select(func.set_config("nexus.company_id", str(COMPANY), True)))
        for model in (JournalAction, EffectIntent, CostHold):
            assert await session.scalar(select(func.count()).select_from(model)) == 1
        hold = await session.get(CostHold, command.action_id)
        assert hold and hold.actual_usd is None and hold.state == "unknown"
