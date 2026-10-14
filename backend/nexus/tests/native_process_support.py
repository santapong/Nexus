"""Actual queue process helpers preserve finite observations and task-owned process cleanup."""

import asyncio
import os
import sys
from pathlib import Path

from dbos import DBOS
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.management.scheduling_contracts import DueWake, ScanRequest, SchedulerPolicy
from nexus.company.management.scheduling_store import ManagementScheduler
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.native_report_contracts import NativeReportResult
from nexus.settings import settings
from nexus.tests.generated_artifact_fixture import GeneratedScenario
from nexus.tests.integration.test_company_directory import OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_native_report_worker import worker_services


async def migrate_system() -> None:
    """Actual pinned DBOS schema/API; normal company migration remains owned by the fixture."""
    url = make_url(settings.company_test_database_url)
    await asyncio.to_thread(
        DBOS.migrate,
        url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
        application_role="nexus_company_app",
    )


async def remove_system() -> None:
    """Remove only this isolated fixture's system schema after owned subprocesses terminate."""
    engine = create_async_engine(settings.company_test_database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS dbos CASCADE"))
    finally:
        await engine.dispose()


async def enqueue_check(
    factory: async_sessionmaker[AsyncSession],
    scenario: GeneratedScenario,
    command: SegmentCommand,
) -> None:
    """Actual owner scheduler scan creates native dispatch and DBOS portable enqueue atomically."""
    services = worker_services(factory, scenario)
    scheduler = ManagementScheduler(
        factory,
        SchedulerServices(
            policy=SchedulerPolicy(
                recipe_version="native-report-process-v1",
                workflows=(services.registration,),
            ),
            catalog=scenario.plans.catalog,
            artifacts=scenario.artifacts,
            freshness=scenario.publisher.freshness,
            identities=services.identities,
            resources=services.resources,
        ),
    )
    from datetime import UTC, datetime

    bucket = datetime.now(UTC).replace(second=0, microsecond=0)
    result = await scheduler.scan(
        control(),
        identity(OWNER),
        ScanRequest(
            company_id=command.company_id,
            wake=DueWake(bucket=bucket),
            task_ids=(command.task_id,),
        ),
    )
    queued = next(row for row in result.receipt.work if row.dispatch == "enqueued")
    assert queued.workflow_id == command.workflow_id and queued.segment_id == command.segment_id


async def spawn_native(
    root: Path, workflow_id: str, *, barrier: str | None = None
) -> asyncio.subprocess.Process:
    """Run the actual registered native worker; process arguments contain no credentials."""
    url = make_url(settings.company_test_database_url).set(username="nexus_company_app")
    arguments = [
        sys.executable,
        "-m",
        "nexus.tests.integration.native_report_process",
        "--root",
        str(root),
        "--workflow-id",
        workflow_id,
    ]
    if barrier is not None:
        arguments.extend(("--barrier", barrier))
    return await asyncio.create_subprocess_exec(
        *arguments,
        cwd=Path(__file__).resolve().parents[2],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={"PATH": os.defpath, "COMPANY_DATABASE_URL": url.render_as_string(hide_password=False)},
    )


async def wait_barrier(process: asyncio.subprocess.Process, root: Path) -> SegmentCommand:
    """A confirmed live handle stays authoritative; observation expiry never starts another job."""
    for _ in range(1400):
        if (root / "barrier-reached").exists():
            return SegmentCommand.model_validate_json((root / "barrier-reached").read_text())
        if process.returncode is not None:
            stdout, stderr = await process.communicate()
            raise AssertionError(
                f"Native process exited before phase: {stdout[-1000:]!r} {stderr[-4000:]!r}"
            )
        await asyncio.sleep(0.05)
    raise AssertionError("Actual native process did not reach its phase within bounded observation")


async def completed_native(process: asyncio.subprocess.Process) -> NativeReportResult:
    """Read the same actual workflow handle result and clean up only the owned process."""
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=105)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise
    assert process.returncode == 0, stderr.decode()[-5000:]
    lines = [
        line.removeprefix("NATIVE_RESULT=")
        for line in stdout.decode().splitlines()
        if line.startswith("NATIVE_RESULT=")
    ]
    assert len(lines) == 1, stdout.decode()[-2000:]
    return NativeReportResult.model_validate_json(lines[0])
