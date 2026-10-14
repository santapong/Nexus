"""Actual OS kill/restart of a scheduler-enqueued native publication/proof workflow."""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.management.acceptance_models import ManagementWorkAcceptance
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.harness.journal_models import CostHold
from nexus.tests.native_process_config import save_process_config
from nexus.tests.native_process_support import (
    completed_native,
    enqueue_check,
    migrate_system,
    remove_system,
    spawn_native,
    wait_barrier,
)
from nexus.tests.native_workflow_support import prepare_check_dispatch, published_author
from nexus.tests.native_workflow_support import workflow_factory as workflow_factory


@pytest.mark.parametrize(
    "phase", ["intent_committed", "artifact_published", "receipt_recorded", "acceptance_recorded"]
)
async def test_actual_native_check_survives_phase_kill_without_another_attempt(
    workflow_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    phase: str,
) -> None:
    await migrate_system()
    first: asyncio.subprocess.Process | None = None
    try:
        scenario = await published_author(workflow_factory, tmp_path / "blobs")
        action, command = await prepare_check_dispatch(workflow_factory, scenario, reserve=False)
        save_process_config(tmp_path, scenario)
        await enqueue_check(workflow_factory, scenario, command)
        first = await spawn_native(tmp_path, command.workflow_id, barrier=phase)
        assert await wait_barrier(first, tmp_path) == command
        async with workflow_factory() as session, session.begin():
            await session.execute(
                select(func.set_config("nexus.company_id", str(command.company_id), True))
            )
            work = await session.get(ExecutionWork, (command.company_id, command.task_id))
            effect = await session.get(EffectIntent, (command.company_id, action.action_id))
            hold = await session.get(CostHold, action.action_id)
            assert work and effect and hold
            receipt_known = phase in {"receipt_recorded", "acceptance_recorded"}
            assert effect.state == ("succeeded" if receipt_known else "intent")
            assert work.tool_attempts_used == 1 and work.model_requests_used == 0
            assert hold.state == ("reconciled" if receipt_known else "held")
            assert hold.actual_usd == (0 if receipt_known else None)
            assert await session.scalar(
                select(func.count()).select_from(ManagementWorkAcceptance)
            ) == (1 if phase == "acceptance_recorded" else 0)
            fence, segment = work.fence, work.segment_number
        first.kill()
        await first.communicate()
        result = await completed_native(await spawn_native(tmp_path, command.workflow_id))
        assert result.status == ("outcome_unknown" if phase == "intent_committed" else "accepted")
        assert (result.acceptance_id is None) == (phase == "intent_committed")
        assert (result.receipt_id is None) == (phase == "intent_committed")
        assert await completed_native(await spawn_native(tmp_path, command.workflow_id)) == result
        async with workflow_factory() as session, session.begin():
            await session.execute(
                select(func.set_config("nexus.company_id", str(command.company_id), True))
            )
            final = await session.get(ExecutionWork, (command.company_id, command.task_id))
            assert final and final.fence > fence and final.segment_number == segment
            assert (
                final.tool_attempts_used == 1
                and final.model_requests_used == 0
                and final.worker_id is None
            )
            assert await session.scalar(
                select(func.count()).select_from(ManagementWorkAcceptance)
            ) == (0 if phase == "intent_committed" else 1)
            final_hold = await session.get(CostHold, action.action_id)
            assert final_hold is not None
            assert final_hold.state == ("unknown" if phase == "intent_committed" else "reconciled")
            assert final_hold.actual_usd == (None if phase == "intent_committed" else 0)
            status = (
                (
                    await session.execute(
                        text(
                            "SELECT status,recovery_attempts FROM dbos.workflow_status "
                            "WHERE workflow_uuid=:id"
                        ),
                        {"id": command.workflow_id},
                    )
                )
                .mappings()
                .one()
            )
            assert status["status"] == "SUCCESS"
        (tmp_path / "native-process-proof.json").write_text(
            json.dumps(
                {
                    "result": result.model_dump(mode="json"),
                    "sdk": dict(status),
                    "original_fence": fence,
                    "final_fence": final.fence,
                    "phase_observations": (tmp_path / "phases.jsonl").read_text().splitlines(),
                    "scope": "actual durable native check/receipt/proof; offline and no models",
                    "interrupted_phase": phase,
                },
                indent=2,
            )
        )
    finally:
        if first is not None and first.returncode is None:
            first.kill()
            await first.communicate()
        await remove_system()
