"""Actual company-profile DBOS/TestModel process and crash acceptance, entirely offline.

Acceptance-fixture size exception: this file keeps one isolated database lifecycle,
complete registered intake, subprocess termination and preserved raw evidence together.
Application worker responsibilities remain split across small typed modules.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from dbos import DBOS
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.access import VerifiedIdentity
from nexus.company.contracts.actions import ActionProposal, ResourceRevision
from nexus.company.contracts.work import WorkItem
from nexus.execution.company_worker_support import (
    MODEL_PROFILE,
    MODEL_REGISTRY_VERSION,
    WorkerPhase,
)
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dbos_queue import APPLICATION_VERSION, WORKFLOW_NAME
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.runtime_contracts import AttemptQuota, ExecutionRegistration, ExecutionSnapshot
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_store import ExecutionStore, next_segment_id
from nexus.harness.authorization_models import ActionAuthority
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_contracts import LedgerScope
from nexus.harness.journal_models import CostHold
from nexus.harness.standing_contracts import StandingGrant, WorkAuthority
from nexus.harness.standing_journal import StandingJournal
from nexus.harness.standing_store import StandingAuthorityStore
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import (
    ACTOR,
    COMPANY,
    OWNER,
    TASK,
    TRACE,
    WORKSPACE,
    control,
    migrate,
    prepare,
    work,
)


@dataclass
class WorkerDatabase:
    app: async_sessionmaker[AsyncSession]
    admin: async_sessionmaker[AsyncSession]
    app_url: str


@pytest.fixture
async def database() -> AsyncIterator[WorkerDatabase]:
    if not settings.company_test_database_url:
        pytest.skip("Explicit private integrated-worker test database is not configured")
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_worker"
    assert settings.company_test_database_url != settings.database_url
    await asyncio.to_thread(
        DBOS.migrate,
        url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
        application_role="nexus_company_app",
    )
    engine, app = (
        create_async_engine(url),
        create_async_engine(url.set(username="nexus_company_app")),
    )
    async with engine.begin() as connection:
        await connection.run_sync(migrate, "upgrade")
    try:
        yield WorkerDatabase(
            async_sessionmaker(app, expire_on_commit=False),
            async_sessionmaker(engine, expire_on_commit=False),
            url.set(username="nexus_company_app").render_as_string(hide_password=False),
        )
    finally:
        await app.dispose()
        async with engine.begin() as connection:
            await connection.run_sync(migrate, "downgrade")
            await connection.execute(text("DROP SCHEMA dbos CASCADE"))
        await engine.dispose()


def scope(principal_id: UUID = ACTOR) -> LedgerScope:
    return LedgerScope(company_id=COMPANY, principal_id=principal_id, task_id=TASK, trace_id=TRACE)


def identity(principal_id: UUID = ACTOR) -> VerifiedIdentity:
    return VerifiedIdentity(principal_id=principal_id, workspace_id=WORKSPACE)


async def registered(database: WorkerDatabase) -> ExecutionSnapshot:
    """Register the same frozen work/quota without submitting or executing an action."""
    directory = await prepare(database.app)
    await directory.register_work(work(), control())
    request = ExecutionRegistration(
        work=WorkItem(
            company_id=COMPANY,
            task_id=TASK,
            trace_id=TRACE,
            goal_id=UUID(int=900),
            department="presentation",
            title="offline draft",
            acceptance=("synthetic-draft",),
            budget_usd=Decimal("1.00"),
        ),
        run_id=UUID(int=901),
        workflow_name=WORKFLOW_NAME,
        workflow_version=APPLICATION_VERSION,
        model_profile=MODEL_PROFILE,
        model_registry_version=MODEL_REGISTRY_VERSION,
        quota=AttemptQuota(),
    )
    return await ExecutionStore(database.app).register(request, scope(), identity())


def draft_action(*, preconditions: bool = False) -> ActionProposal:
    return ActionProposal(
        company_id=COMPANY,
        action_id=UUID(int=902),
        task_id=TASK,
        trace_id=TRACE,
        actor_id=ACTOR,
        revision=1,
        tool="fake.internal.draft.v1",
        tool_version="v1",
        resource="fixture:report",
        parameters={"draft": "Synthetic readiness draft"},
        policy_version="fixture-policy",
        price_version="fixture-prices",
        estimated_cost_usd=Decimal("0.10"),
        preconditions=(ResourceRevision(resource="fixture:report", revision="offline-v1"),)
        if preconditions
        else (),
    )


async def queued(
    database: WorkerDatabase, *, standing: bool = False, preconditions: bool = False
) -> SegmentCommand:
    snapshot = await registered(database)
    action = draft_action(preconditions=preconditions)
    journal = CompanyJournal(database.app)
    record = await journal.submit(action, scope())
    now = datetime.now(UTC)
    if not standing:
        await journal.approve_registered(
            scope(OWNER), action.action_id, record.proposal_hash, now, identity=identity(OWNER)
        )
    command = SegmentCommand(
        company_id=COMPANY,
        task_id=TASK,
        trace_id=TRACE,
        actor_id=ACTOR,
        workspace_id=WORKSPACE,
        run_id=snapshot.registration.run_id,
        action_id=action.action_id,
        segment_id=next_segment_id(snapshot),
    )
    if standing:
        await authorize_standing(database, command, action, now)
    else:
        await journal.authorize_and_enqueue_registered(
            scope(), command, now, action.preconditions, identity=identity()
        )
    return command


async def authorize_standing(
    database: WorkerDatabase, command: SegmentCommand, action: ActionProposal, now: datetime
) -> None:
    store = StandingAuthorityStore(database.app)
    binding = WorkAuthority(
        company_id=COMPANY,
        task_id=TASK,
        plan_id=UUID(int=950),
        plan_revision=1,
        charter_id=UUID(int=951),
        charter_revision=1,
    )
    await store.bind_work(binding, control(), identity(OWNER))
    grant = StandingGrant(
        **binding.model_dump(),
        grant_id=UUID(int=952),
        owner_id=OWNER,
        actor_id=ACTOR,
        issued_at=now,
        expires_at=now + timedelta(hours=8),
        policy_version="fixture-policy",
        price_version="fixture-prices",
        max_action_cost_usd=Decimal("0.50"),
        permissions=(
            {"tool": action.tool, "tool_version": action.tool_version, "resource": action.resource},
        ),
    )
    await store.issue(grant, control(), identity(OWNER), now)
    await StandingJournal(database.app).authorize_and_enqueue_standing(
        scope(), command, grant.grant_id, now, action.preconditions, identity=identity()
    )


async def spawn(
    database: WorkerDatabase,
    command: SegmentCommand,
    root: Path,
    barrier: str | None = None,
    resource_version: str = "offline-v1",
    *,
    application_version: str | None = None,
    observation_seconds: float | None = None,
    fault_phase: WorkerPhase | None = None,
) -> asyncio.subprocess.Process:
    args = [
        sys.executable,
        "-m",
        "nexus.tests.integration.company_worker_process",
        "--workflow-id",
        command.workflow_id,
        "--artifacts",
        str(root / "artifacts"),
        "--evidence",
        str(root / "evidence"),
    ]
    if barrier:
        args.extend(("--barrier", barrier))
    args.extend(("--resource-version", resource_version))
    if application_version is not None:
        args.extend(("--application-version", application_version))
    if observation_seconds is not None:
        args.extend(("--observation-seconds", str(observation_seconds)))
    if fault_phase is not None:
        args.extend(("--fault-phase", fault_phase))
    return await asyncio.create_subprocess_exec(
        *args,
        cwd=Path(__file__).resolve().parents[3],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={"PATH": os.defpath, "COMPANY_DATABASE_URL": database.app_url},
    )


async def completed(
    process: asyncio.subprocess.Process, *, marker: str = "WORKER_RESULT=", timeout: float = 45
) -> dict[str, object]:
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise
    assert process.returncode == 0, stderr.decode()[-6000:]
    lines = [
        line[len(marker) :] for line in stdout.decode().splitlines() if line.startswith(marker)
    ]
    assert len(lines) == 1, stdout.decode()
    decoded: object = json.loads(lines[0])
    assert isinstance(decoded, dict)
    result: dict[str, object] = {}
    for key, value in decoded.items():
        assert isinstance(key, str)
        result[key] = value
    return result


async def barrier_reached(process: asyncio.subprocess.Process, root: Path, phase: str) -> None:
    for _ in range(300):
        if (root / "evidence" / phase).exists():
            return
        if process.returncode is not None:
            stdout, stderr = await process.communicate()
            pytest.fail(
                f"Worker exited before barrier: {stdout.decode()} {stderr.decode()[-3000:]}"
            )
        await asyncio.sleep(0.05)
    process.kill()
    stdout, stderr = await process.communicate()
    pytest.fail(f"Worker barrier timed out: {stdout.decode()} {stderr.decode()[-3000:]}")


async def state(database: WorkerDatabase) -> tuple[ExecutionWork, EffectIntent, CostHold]:
    async with database.admin() as session:
        execution = await session.get(ExecutionWork, (COMPANY, TASK))
        effect = await session.get(EffectIntent, (COMPANY, UUID(int=902)))
        hold = await session.get(CostHold, UUID(int=902))
        assert execution and effect and hold
        return execution, effect, hold


async def save_proof(
    database: WorkerDatabase, command: SegmentCommand, root: Path, result: dict[str, object]
) -> None:
    """Preserve scoped raw business/SDK evidence before the disposable fixture is removed."""
    async with database.admin() as session:
        sdk = (
            (
                await session.execute(
                    text(
                        "SELECT status,name,application_version,serialization "
                        "FROM dbos.workflow_status "
                        "WHERE workflow_uuid=:id"
                    ),
                    {"id": command.workflow_id},
                )
            )
            .mappings()
            .one()
        )
        execution = await session.get(ExecutionWork, (COMPANY, TASK))
        effect = await session.get(EffectIntent, (COMPANY, command.action_id))
        hold = await session.get(CostHold, command.action_id)
        assert execution is not None and hold is not None
        payload = {
            "command": command.model_dump(mode="json"),
            "sdk": dict(sdk),
            "result": result,
            "business_state": execution.state,
            "model_requests": execution.model_requests_used,
            "tool_attempts": execution.tool_attempts_used,
            "fence": execution.fence,
            "segment_number": execution.segment_number,
            "worker_released": execution.worker_id is None,
            "effect_state": effect.state if effect else None,
            "receipt": json.loads(effect.receipt_json) if effect and effect.receipt_json else None,
            "verification_candidate": json.loads(effect.verification_json)
            if effect and effect.verification_json
            else None,
            "hold_state": hold.state,
            "held_usd": str(hold.amount_usd),
            "actual_usd": str(hold.actual_usd) if hold.actual_usd is not None else None,
        }
        await asyncio.to_thread((root / "proof.json").write_text, json.dumps(payload, indent=2))


async def test_real_worker_records_offline_model_tool_receipt_and_candidate(
    database: WorkerDatabase, tmp_path: Path
) -> None:
    command = await queued(database)
    result = await completed(await spawn(database, command, tmp_path))
    execution, effect, hold = await state(database)
    assert result["status"] == execution.state == "verifying"
    assert (execution.model_requests_used, execution.tool_attempts_used) == (1, 1)
    assert execution.worker_id is None and effect.state == "succeeded"
    assert effect.receipt_json and effect.verification_json
    assert json.loads(effect.verification_json)["verdict"] == "inconclusive"
    assert hold.state == "reconciled" and hold.actual_usd == 0
    events = (tmp_path / "evidence" / "events.jsonl").read_text().splitlines()
    assert sum(json.loads(event)["phase"] == "model_called" for event in events) == 1
    await save_proof(database, command, tmp_path, result)


@pytest.mark.parametrize(
    "phase,expected",
    [
        ("intent_committed", "outcome_unknown"),
        ("output_saved", "verifying"),
        ("receipt_recorded", "verifying"),
    ],
)
async def test_process_kill_never_replays_one_time_effect_permission(
    database: WorkerDatabase, tmp_path: Path, phase: str, expected: str
) -> None:
    command = await queued(database)
    first = await spawn(database, command, tmp_path, phase)
    await barrier_reached(first, tmp_path, phase)
    first.kill()
    await first.communicate()
    result = await completed(await spawn(database, command, tmp_path))
    execution, effect, hold = await state(database)
    assert result["status"] == execution.state == expected
    assert execution.model_requests_used == 1 and execution.worker_id is None
    events = (tmp_path / "evidence" / "events.jsonl").read_text().splitlines()
    calls = sum(json.loads(event)["phase"] == "model_called" for event in events)
    assert calls == (0 if phase == "intent_committed" else 1)
    if expected == "outcome_unknown":
        assert effect.state == "outcome_unknown"
        assert hold.state == "unknown" and hold.actual_usd is None
    else:
        assert effect.state == "succeeded" and hold.state == "reconciled"
    await save_proof(database, command, tmp_path, result)


async def test_pause_between_queue_and_worker_causes_no_model_call(
    database: WorkerDatabase, tmp_path: Path
) -> None:
    command = await queued(database)
    await CompanyJournal(database.app).set_paused(scope(OWNER), True)
    result = await completed(await spawn(database, command, tmp_path))
    assert result["status"] == "blocked"
    assert not (tmp_path / "evidence" / "model_called").exists()
    async with database.admin() as session:
        assert await session.get(EffectIntent, (COMPANY, command.action_id)) is None
    await save_proof(database, command, tmp_path, result)


async def test_standing_plan_grant_runs_actual_worker_without_an_exact_action_decision(
    database: WorkerDatabase,
    tmp_path: Path,
) -> None:
    command = await queued(database, standing=True)
    result = await completed(await spawn(database, command, tmp_path))
    execution, effect, hold = await state(database)
    assert result["status"] == execution.state == "verifying"
    assert effect.state == "succeeded" and hold.actual_usd == 0
    async with database.admin() as session:
        source = await session.get(ActionAuthority, (COMPANY, command.action_id))
        assert source is not None and source.grant_id == UUID(int=952)
    await save_proof(database, command, tmp_path, result)


async def test_resource_revision_is_refreshed_from_server_registry_after_queue_wait(
    database: WorkerDatabase,
    tmp_path: Path,
) -> None:
    command = await queued(database, preconditions=True)
    result = await completed(await spawn(database, command, tmp_path, resource_version="changed"))
    assert result["status"] == "blocked"
    async with database.admin() as session:
        stored = await session.get(ExecutionWork, (COMPANY, TASK))
        assert stored is not None and stored.state == "blocked"
        assert stored.worker_id is None and stored.lease_principal_id is None
    assert not (tmp_path / "evidence" / "model_called").exists()
    async with database.admin() as session:
        assert await session.get(EffectIntent, (COMPANY, command.action_id)) is None
    await save_proof(database, command, tmp_path, result)


async def test_incompatible_version_leaves_dispatch_held_until_compatible_worker(
    database: WorkerDatabase, tmp_path: Path
) -> None:
    command = await queued(database)
    first = await spawn(
        database,
        command,
        tmp_path,
        application_version="company-v0.2-incompatible-test",
        observation_seconds=1,
    )
    observation = await completed(first, marker="WORKER_UNMATCHED=", timeout=20)
    assert observation["application_version"] == "company-v0.2-incompatible-test"
    assert observation["workflow_id"] == command.workflow_id
    assert not (tmp_path / "evidence" / "model_called").exists()
    async with database.admin() as session:
        work = await session.get(ExecutionWork, (COMPANY, TASK))
        hold = await session.get(CostHold, command.action_id)
        dispatch = await session.get(SegmentDispatch, (COMPANY, command.action_id))
        assert work is not None and hold is not None and dispatch is not None
        assert work.state == "eligible" and work.model_requests_used == work.tool_attempts_used == 0
        assert work.worker_id is None and work.segment_number == work.fence == 0
        assert (
            hold.state == "held" and hold.actual_usd is None and hold.amount_usd == Decimal("0.10")
        )
        assert (
            dispatch.binding_json == command.model_dump_json()
            and dispatch.workflow_id == command.workflow_id
        )
        assert await session.get(EffectIntent, (COMPANY, command.action_id)) is None
        sdk = (
            (
                await session.execute(
                    text(
                        "SELECT status,application_version,recovery_attempts "
                        "FROM dbos.workflow_status WHERE workflow_uuid=:id"
                    ),
                    {"id": command.workflow_id},
                )
            )
            .mappings()
            .one()
        )
        assert sdk["status"] == "ENQUEUED" and sdk["application_version"] == APPLICATION_VERSION
        assert sdk["recovery_attempts"] == 0
    (tmp_path / "unmatched.json").write_text(json.dumps(observation, indent=2))
    result = await completed(await spawn(database, command, tmp_path))
    execution, effect, hold = await state(database)
    assert result["status"] == execution.state == "verifying"
    assert (
        execution.model_requests_used,
        execution.tool_attempts_used,
        execution.segment_number,
    ) == (1, 1, 1)
    assert effect.state == "succeeded" and hold.state == "reconciled" and hold.actual_usd == 0
    events = (tmp_path / "evidence" / "events.jsonl").read_text().splitlines()
    assert sum(json.loads(event)["phase"] == "model_called" for event in events) == 1
    async with database.admin() as session:
        dispatch = await session.get(SegmentDispatch, (COMPANY, command.action_id))
        assert dispatch is not None and dispatch.segment_id == command.segment_id
        assert (
            dispatch.binding_json == command.model_dump_json()
            and dispatch.workflow_id == command.workflow_id
        )
    await save_proof(database, command, tmp_path, result)


async def test_post_model_value_error_returns_persisted_unknown_and_never_reissues(
    database: WorkerDatabase, tmp_path: Path
) -> None:
    command = await queued(database)
    result = await completed(await spawn(database, command, tmp_path, fault_phase="model_called"))
    execution, effect, hold = await state(database)
    assert result["status"] == execution.state == effect.state == "outcome_unknown"
    assert execution.model_requests_used == 1 and execution.tool_attempts_used == 0
    assert execution.worker_id is None and effect.receipt_json is None
    assert (
        hold.state == "unknown" and hold.amount_usd == Decimal("0.10") and hold.actual_usd is None
    )
    replay = await completed(await spawn(database, command, tmp_path))
    assert replay == result
    execution, effect, hold = await state(database)
    assert execution.state == effect.state == "outcome_unknown"
    assert execution.model_requests_used == 1 and execution.tool_attempts_used == 0
    assert (
        hold.state == "unknown" and hold.amount_usd == Decimal("0.10") and hold.actual_usd is None
    )
    events = (tmp_path / "evidence" / "events.jsonl").read_text().splitlines()
    assert sum(json.loads(event)["phase"] == "model_called" for event in events) == 1
    await save_proof(database, command, tmp_path, result)


async def test_owner_wait_releases_segment_then_resumes_same_run_and_lifetime_budget(
    database: WorkerDatabase, tmp_path: Path
) -> None:
    initial = await registered(database)
    execution = ExecutionStore(database.app)
    lease = await execution.claim(scope(), identity(), UUID(int=997), ttl_seconds=60)
    assert lease.run_id == initial.registration.run_id
    action = draft_action()
    journal = CompanyJournal(database.app)
    pending = await journal.submit(action, scope())
    waiting = await execution.await_approval(lease, identity(), action.action_id)
    assert waiting.state == "awaiting_approval" and waiting.segment_number == 1
    assert waiting.worker_id is None and waiting.lease_principal_id is None
    assert waiting.registration == initial.registration and waiting.counters == initial.counters
    assert waiting.waiting_action_id == action.action_id
    now = datetime.now(UTC)
    approved = await CompanyJournal(database.app).approve_registered(
        scope(OWNER), action.action_id, pending.proposal_hash, now, identity=identity(OWNER)
    )
    assert approved.approval is not None and approved.approval.approver_id == OWNER
    command = SegmentCommand(
        company_id=COMPANY,
        task_id=TASK,
        trace_id=TRACE,
        actor_id=ACTOR,
        workspace_id=WORKSPACE,
        run_id=initial.registration.run_id,
        action_id=action.action_id,
        segment_id=next_segment_id(waiting),
    )
    assert command.segment_id != lease.segment_id
    await journal.authorize_and_enqueue_registered(scope(), command, now, (), identity=identity())
    result = await completed(await spawn(database, command, tmp_path))
    current = await execution.get(scope(), identity())
    assert (
        current.registration == initial.registration
        and current.registration.quota == initial.registration.quota
    )
    assert current.registration.work.budget_usd == Decimal("1.00")
    assert current.segment_number == 2 and current.state == result["status"] == "verifying"
    assert current.counters.model_requests == current.counters.tool_attempts == 1
    assert current.worker_id is None and current.lease_principal_id is None
    record = await journal.get_action(scope(), action.action_id)
    assert record.proposal_hash == pending.proposal_hash and record.approval == approved.approval
    async with database.admin() as session:
        assert await session.get(ActionAuthority, (COMPANY, action.action_id)) is None
        hold = await session.get(CostHold, action.action_id)
        assert (
            hold is not None and hold.amount_usd == Decimal("0.10") and hold.state == "reconciled"
        )
    (tmp_path / "waiting.json").write_text(waiting.model_dump_json())
    await save_proof(database, command, tmp_path, result)
