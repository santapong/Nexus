"""Actual OS kill/restart of scheduler-enqueued DBOS workflow, without model/effect claims."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_contracts import ExecutionLease, ExecutionSnapshot
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import registration_digest
from nexus.harness.journal_models import CostHold
from nexus.settings import settings
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


async def spawn(
    root: Path, workflow_id: str, *, barrier: bool = False
) -> asyncio.subprocess.Process:
    url = make_url(settings.company_test_database_url).set(username="nexus_company_app")
    args = [
        sys.executable,
        "-m",
        "nexus.tests.integration.management_scheduler_process",
        "--workflow-id",
        workflow_id,
        "--root",
        str(root),
    ]
    if barrier:
        args.append("--barrier")
    return await asyncio.create_subprocess_exec(
        *args,
        cwd=Path(__file__).resolve().parents[3],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={"PATH": os.defpath, "COMPANY_DATABASE_URL": url.render_as_string(hide_password=False)},
    )


async def wait_claimed(process: asyncio.subprocess.Process, root: Path) -> ExecutionLease:
    for _ in range(300):
        if (root / "claimed").exists():
            return ExecutionLease.model_validate_json((root / "claimed").read_text())
        if process.returncode is not None:
            stdout, stderr = await process.communicate()
            raise AssertionError(f"Process exited before claim: {stdout!r} {stderr[-3500:]!r}")
        await asyncio.sleep(0.05)
    raise AssertionError("Actual DBOS process did not acquire native dispatch in bounded time")


async def completed(process: asyncio.subprocess.Process) -> ExecutionSnapshot:
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise
    assert process.returncode == 0, stderr.decode()[-5000:]
    results = [
        line.removeprefix("SCHEDULER_RESULT=")
        for line in stdout.decode().splitlines()
        if line.startswith("SCHEDULER_RESULT=")
    ]
    assert len(results) == 1, stdout.decode()
    return ExecutionSnapshot.model_validate_json(results[0])


async def test_actual_queue_process_kill_reuses_same_dispatch_segment_and_lifetime_slices(
    scheduler_database: SchedulerDatabase,
    tmp_path: Path,
) -> None:
    scheduler, payload = await setup_scheduler(scheduler_database, tmp_path / "blobs")
    author = payload.children[0].binding
    action = await authorized_action(scheduler_database.app, author)
    receipt = (
        await scheduler.scan(control(), identity(OWNER), await due_request(scheduler_database))
    ).receipt
    queued = next(row for row in receipt.work if row.dispatch == "enqueued")
    assert queued.workflow_id is not None and queued.segment_id is not None
    (tmp_path / "catalog.json").write_text(scheduler.services.catalog.model_dump_json())
    first = await spawn(tmp_path, queued.workflow_id, barrier=True)
    try:
        lease = await wait_claimed(first, tmp_path)
        during = await scheduler.scan(
            control(),
            identity(OWNER),
            await due_request(scheduler_database, task_ids=(author.task_id,)),
        )
        assert during.receipt.work[0].eligibility.reason == "dispatch_active"
    finally:
        if first.returncode is None:
            first.kill()
        await first.communicate()
    await asyncio.sleep(2.1)
    result = await completed(await spawn(tmp_path, queued.workflow_id))
    replay = await completed(await spawn(tmp_path, queued.workflow_id))
    assert replay == result and result.segment_id == lease.segment_id == queued.segment_id
    assert result.segment_number == 1 and result.fence > lease.fence
    assert result.registration.run_id == author.run_id and result.worker_id is None
    assert result.counters.model_requests == result.counters.tool_attempts == 0
    leases = [
        ExecutionLease.model_validate_json(line)
        for line in (tmp_path / "leases.jsonl").read_text().splitlines()
    ]
    assert len(leases) == 2 and leases[1].fence > leases[0].fence
    async with scheduler_database.admin() as session:
        dispatch = await session.get(SegmentDispatch, (COMPANY, action.action_id))
        work = await session.get(ExecutionWork, (COMPANY, author.task_id))
        hold = await session.get(CostHold, action.action_id)
        assert dispatch and dispatch.segment_id == queued.segment_id and work and hold
        assert work.registration_hash == registration_digest(result.registration)
        assert work.run_id == author.run_id and work.tool_attempts_limit == 1
        assert hold.state == "held" and hold.actual_usd is None
        assert await session.scalar(select(func.count()).select_from(SegmentDispatch)) == 1
        assert await session.scalar(select(func.count()).select_from(EffectIntent)) == 0
        status = (
            (
                await session.execute(
                    text(
                        "SELECT status,recovery_attempts FROM dbos.workflow_status "
                        "WHERE workflow_uuid=:id"
                    ),
                    {"id": queued.workflow_id},
                )
            )
            .mappings()
            .one()
        )
        assert status["status"] == "SUCCESS"
    (tmp_path / "recovery-proof.json").write_text(
        json.dumps(
            {
                "command": json.loads(dispatch.binding_json),
                "sdk": dict(status),
                "result": result.model_dump(mode="json"),
                "leases": [row.model_dump(mode="json") for row in leases],
                "scope": "queue delivery and same-dispatch claim recovery; no effect/acceptance",
            },
            indent=2,
        )
    )
