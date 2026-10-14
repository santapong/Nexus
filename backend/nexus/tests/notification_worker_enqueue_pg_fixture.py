"""TEST-only owned normal015/public DBOS schema and one prior explicit owner decision."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from dbos import DBOS
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.management.base import ValueContract
from nexus.company.management.native_profile_admission import ledger_scope
from nexus.company.management.scheduling_contracts import SchedulerPolicy
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.dispatch_store import NotificationTransportConfiguration
from nexus.company.notifications.managed_contracts import NativeNotificationSelection
from nexus.company.notifications.managed_effects import ManagedNotificationEffectStore
from nexus.company.notifications.observation_models import NotificationObservationRow
from nexus.company.notifications.worker_config import WorkerRegistrationSnapshot
from nexus.company.notifications.worker_dispatch import AuthenticatedManagedNotificationDispatcher
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.notifications.worker_tick import NotificationReadPreparationWorker
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.dispatch_models import SegmentDispatch
from nexus.execution.notification_worker_services import (
    NotificationDispatchWorkerServices,
    notification_workflow_registration,
)
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt, ExecutionWork
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import db_now
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_models import CostHold, JournalAction
from nexus.settings import settings
from nexus.tests.integration.test_company_directory import control, migrate
from nexus.tests.notification_worker_tick_fixture import worker_tick_native_case
from nexus.tests.notification_worker_tick_services_fixture import configured_tick_services

_DATABASE = "nexus_company_test_notification_enqueue_atomic"
_SOCKET = "/tmp/nexus-release-tests-2026-10-13/socket"


@dataclass(frozen=True)
class AtomicNotificationDatabases:
    """Only the one assigned database's actual admin and restricted application factories."""

    app: async_sessionmaker[AsyncSession]
    admin: async_sessionmaker[AsyncSession]


@dataclass(frozen=True)
class AtomicNotificationCase:
    """Actual public fixture pins and sealed synthetic witness; no issued effect."""

    services: NotificationDispatchWorkerServices
    selection: NativeNotificationSelection
    credential: AuthenticatedWorkerIdentity
    snapshot: WorkerRegistrationSnapshot
    source_action_id: UUID
    decision_sha256: str
    http_calls: list[str]


class AtomicEnqueueLedger(ValueContract):
    """Safe recorded fixture metadata; no private body, token or provider authority."""

    action_state: str
    consumed_at: datetime | None
    decision_sha256: str
    hold: tuple[str, str | None, str]
    dispatch_count: int
    workflow_count: int
    queue_status: str
    queue_binding_sha256: str
    canonical_binding: bool
    effect_counts: tuple[int, ...]
    counters: tuple[tuple[UUID, int, int], ...]
    source_action_state: str
    database: str
    business_role: str


@pytest.fixture
async def atomic_notification_databases() -> AsyncIterator[AtomicNotificationDatabases]:
    """No use until Root releases this exact source/DB packet; no SDK worker is launched."""
    # Cohesive >50-line fixture exception: exact empty DB/role checks, public
    # schema installation and owned normal teardown must retain one closed scope.
    if not settings.company_test_database_url:
        pytest.skip("Explicit owned atomic notification fixture is not configured")
    url = make_url(settings.company_test_database_url)
    assert (
        url.drivername,
        url.username,
        url.password,
        url.host,
        url.port,
        url.database,
    ) == ("postgresql+asyncpg", "santapong", None, None, None, _DATABASE)
    assert dict(url.query) == {"host": _SOCKET, "port": "55438"}
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    installed = False
    try:
        async with admin.begin() as connection:
            assert await connection.scalar(text("SELECT current_database()")) == _DATABASE
            assert await connection.scalar(text("SELECT current_user")) == "santapong"
            tables = tuple(
                (
                    await connection.scalars(
                        text(
                            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                            "ORDER BY tablename"
                        )
                    )
                ).all()
            )
            assert tables in ((), ("company_alembic_version",))
            if tables:
                assert (
                    await connection.scalar(text("SELECT count(*) FROM company_alembic_version"))
                    == 0
                )
            assert (
                await connection.scalar(text("SELECT to_regclass('dbos.workflow_status')")) is None
            )
        await asyncio.to_thread(
            DBOS.migrate,
            url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
            application_role="nexus_company_app",
        )
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        installed = True
        async with app.connect() as connection:
            assert await connection.scalar(text("SELECT current_database()")) == _DATABASE
            assert await connection.scalar(text("SELECT current_user")) == "nexus_company_app"
            assert await connection.scalar(text("SELECT current_setting('port')")) == "55438"
            assert (
                await connection.scalar(
                    text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
                )
                is False
            )
        yield AtomicNotificationDatabases(
            async_sessionmaker(app, expire_on_commit=False),
            async_sessionmaker(admin, expire_on_commit=False),
        )
    finally:
        await app.dispose()
        if installed:
            async with admin.begin() as connection:
                await connection.execute(text("TRUNCATE company_brain_events CASCADE"))
                await connection.run_sync(migrate, "downgrade")
                await connection.execute(text("DROP SCHEMA dbos CASCADE"))
        await admin.dispose()


async def atomic_notification_case(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
) -> AtomicNotificationCase:
    """Stage one real pending notification and commit its prior exact public owner decision."""
    # Cohesive >50-line fixture exception: one real staged sender and its explicit
    # prior public owner decision are constructed together without any effect call.
    native = await worker_tick_native_case(factory, root / "blobs")
    reads = await configured_tick_services(factory, root, native)
    staged = await NotificationReadPreparationWorker(reads, enabled=True).tick()
    assert len(staged.draft_ids) == len(staged.action_ids) == 1
    snapshot = reads.registrations.snapshot()
    binding = snapshot.value.registration.sender
    credential = await reads.identities.current(expected_binding=binding)
    selection = NativeNotificationSelection(
        company_id=binding.company_id,
        sender_task_id=binding.task_id,
        draft_id=staged.draft_ids[0],
        plan=snapshot.value.registration.plan,
    )
    journal, scope = CompanyJournal(factory), ledger_scope(binding)
    record = await journal.get_action(scope, staged.action_ids[0])
    assert record.approval is None and record.consumed_at is None
    async with management_owner_transaction(factory, control(), credential.identity) as (
        session,
        _,
        _,
    ):
        now = await db_now(session)
    await journal.approve_registered(
        scope,
        record.proposal.action_id,
        record.proposal_hash,
        now,
        identity=credential.identity,
    )
    decision = await journal.get_action(scope, record.proposal.action_id)
    assert decision.approval is not None and decision.consumed_at is None
    calls: list[str] = []

    def unexpected_http(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        raise AssertionError("Atomic enqueue must issue no HTTP method")

    effects = ManagedNotificationEffectStore(
        factory,
        reads.drafts,
        reads.facts.catalog,
        reads.facts.artifacts,
        reads.facts.freshness,
        policy=reads.preparation.policy,
    )
    dispatcher = AuthenticatedManagedNotificationDispatcher(
        factory,
        reads.drafts,
        effects,
        enabled=True,
        configuration=NotificationTransportConfiguration(
            enabled=True,
            api_key=SecretStr("synthetic-unused-atomic-queue-only"),
            http_transport=httpx.MockTransport(unexpected_http),
        ),
    )
    execution = ExecutionStore(
        factory,
        management_catalog=reads.facts.catalog,
        management_artifacts=reads.facts.artifacts,
        management_freshness=reads.facts.freshness,
    )
    scheduler = SchedulerServices(
        SchedulerPolicy(
            recipe_version="notification-dispatch-v1",
            max_tasks=1,
            workflows=(notification_workflow_registration(),),
        ),
        reads.facts.catalog,
        reads.facts.artifacts,
        reads.facts.freshness,
        reads.facts.scheduler.identities,
        reads.facts.scheduler.resources,
    )
    services = NotificationDispatchWorkerServices(
        reads,
        execution,
        dispatcher,
        scheduler,
        worker_id=UUID(int=860),
        enabled=True,
    )
    return AtomicNotificationCase(
        services,
        selection,
        credential,
        snapshot,
        native.source_action.action_id,
        hashlib.sha256(decision.approval.model_dump_json().encode()).hexdigest(),
        calls,
    )


async def enqueue_ledger(
    databases: AtomicNotificationDatabases,
    case: AtomicNotificationCase,
    command: SegmentCommand,
) -> AtomicEnqueueLedger:
    """Read actual receipt-free native and DBOS metadata, without private bodies or effects."""
    # Cohesive >50-line actual read-only snapshot: all scalar comparisons belong
    # to the same native owner/company view, with separate body-free DBOS ABI readback.
    async with management_owner_transaction(databases.app, control(), case.credential.identity) as (
        session,
        _,
        _,
    ):
        action = await session.get(JournalAction, command.action_id)
        hold = await session.get(CostHold, command.action_id)
        dispatch = await session.get(SegmentDispatch, (command.company_id, command.action_id))
        source = await session.get(JournalAction, case.source_action_id)
        assert (
            action is not None and hold is not None and dispatch is not None and source is not None
        )
        assert action.approval_json is not None and source.approval_json is None
        dispatch_count = await session.scalar(select(func.count()).select_from(SegmentDispatch))
        assert dispatch_count is not None
        effects = []
        for table in (
            EffectIntent,
            ExecutionAttempt,
            NotificationDispatchRow,
            NotificationObservationRow,
        ):
            count = await session.scalar(select(func.count()).select_from(table))
            assert count is not None
            effects.append(count)
        works = tuple(
            (await session.scalars(select(ExecutionWork).order_by(ExecutionWork.task_id))).all()
        )
        counters = tuple(
            (row.task_id, row.model_requests_used, row.tool_attempts_used) for row in works
        )
        actual_database = await session.scalar(text("SELECT current_database()"))
        actual_role = await session.scalar(text("SELECT current_user"))
        assert isinstance(actual_database, str) and isinstance(actual_role, str)
    async with databases.admin() as session:
        total = await session.scalar(text("SELECT count(*) FROM dbos.workflow_status"))
        saved = (
            (
                await session.execute(
                    text(
                        "SELECT ws.name,ws.queue_name,ws.application_version,ws.application_name,"
                        "ws.serialization,ws.status,wi.inputs FROM dbos.workflow_status ws "
                        "JOIN dbos.workflow_input wi ON wi.workflow_uuid=ws.workflow_uuid "
                        "WHERE ws.workflow_uuid=:workflow_id"
                    ),
                    {"workflow_id": command.workflow_id},
                )
            )
            .mappings()
            .one()
        )
        assert isinstance(total, int)
        encoded = json.dumps(dict(saved), sort_keys=True, default=str)
        assert isinstance(saved["status"], str)
        registration = notification_workflow_registration()
        canonical = (
            dispatch.binding_json == command.model_dump_json()
            and dispatch.workflow_id == command.workflow_id
            and (
                saved["name"],
                saved["queue_name"],
                saved["application_version"],
                saved["application_name"],
                saved["serialization"],
            )
            == (
                registration.workflow_name,
                registration.queue_name,
                registration.workflow_version,
                registration.application_name,
                "portable_json",
            )
            and json.loads(saved["inputs"])
            == {"positionalArgs": [command.model_dump_json()], "namedArgs": {}}
        )
    return AtomicEnqueueLedger(
        action_state=action.state,
        consumed_at=action.consumed_at,
        decision_sha256=hashlib.sha256(action.approval_json.encode()).hexdigest(),
        hold=(
            str(hold.amount_usd),
            str(hold.actual_usd) if hold.actual_usd is not None else None,
            hold.state,
        ),
        dispatch_count=dispatch_count,
        workflow_count=total,
        queue_status=saved["status"],
        queue_binding_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
        canonical_binding=canonical,
        effect_counts=tuple(effects),
        counters=counters,
        source_action_state=source.state,
        database=actual_database,
        business_role=actual_role,
    )
