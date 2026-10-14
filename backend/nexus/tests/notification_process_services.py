"""TEST-only trusted process reconstruction; full current native authority remains in production."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import httpx
from pydantic import SecretStr
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.brain.source_models import BrainSourceHead
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.native_profile_admission import ledger_scope
from nexus.company.management.scheduling_contracts import SchedulerPolicy, WorkflowRegistration
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.dispatch_store import NotificationTransportConfiguration
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.company.notifications.native_loader import NativeNotificationFactLoader
from nexus.company.notifications.observation_models import NotificationObservationRow
from nexus.company.notifications.qualified_adapter import QualifiedNotificationFactAdapter
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.company.notifications.recipient_registry import FileOwnerRecipients
from nexus.company.notifications.worker_config import FileNotificationWorkerRegistration
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    NotificationWorkerIdentities,
    OpaqueCredentialProvider,
)
from nexus.company.notifications.worker_services import NotificationWorkerServices
from nexus.execution.notification_dispatch_read import (
    require_issued_binding,
    require_notification_command,
)
from nexus.execution.notification_worker_services import (
    NotificationDispatchWorkerServices,
    notification_workflow_registration,
)
from nexus.execution.runtime_models import EffectIntent, ExecutionAttempt
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import db_now, execution_row, runtime_transaction
from nexus.harness.canonical import action_hash
from nexus.harness.journal_models import CostHold, JournalAction
from nexus.tests.integration.management_acceptance_source_fixture import Policies
from nexus.tests.management_scheduler_support import FixtureIdentities, FixtureResources
from nexus.tests.notification_durable_pg_fixture import qualified_durable_url
from nexus.tests.notification_preserved_history_support import (
    HistoricalOnlyBlobs,
    HistoricalOnlyDrafts,
    HistoricalSQLBodyGuard,
)
from nexus.tests.notification_process_config import (
    NotificationBarrier,
    NotificationProcessConfig,
    NotificationProcessDatabase,
    require_notification_process_root,
)
from nexus.tests.notification_process_wrappers import (
    InstrumentedNotificationDispatcher,
    InstrumentedNotificationEffects,
    NotificationProcessBarrier,
    append_process_marker,
)
from nexus.tests.notification_worker_credential_fixture import TEST_KEY


async def process_app_backends(database: NotificationProcessDatabase) -> int:
    """Exact assigned DB only; exclude this temporary verification connection, then close it."""
    engine = create_async_engine(
        qualified_durable_url(database).set(username="nexus_company_app"), poolclass=NullPool
    )
    try:
        async with engine.connect() as connection:
            value = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname=current_database() AND usename=current_user "
                    "AND pid<>pg_backend_pid()"
                )
            )
            assert isinstance(value, int)
            return value
    finally:
        await engine.dispose()


async def native_state(
    config: NotificationProcessConfig, witness: AuthenticatedWorkerIdentity
) -> dict[str, object]:
    """Actual body-free owner/member/native state and server clock, with no repair mutation."""
    # Cohesive snapshot: immutable original issued records and live lease fields
    # are compared under one actual company lock; metadata only, no draft body.
    url = qualified_durable_url(config.database).set(username="nexus_company_app")
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with runtime_transaction(
            factory,
            ledger_scope(config.registration.value.registration.sender),
            witness.identity,
            allow_paused=True,
            allow_inactive=True,
        ) as (session, control, _):
            work = await execution_row(
                session, ledger_scope(config.registration.value.registration.sender)
            )
            assert control.owner_id == witness.identity.principal_id
            intent = await session.get(
                EffectIntent, (config.command.company_id, config.command.action_id)
            )
            slot = await session.get(
                NotificationDispatchRow, (config.command.company_id, config.selection.draft_id)
            )
            hold = await session.get(CostHold, config.command.action_id)
            assert intent is not None and slot is not None and hold is not None
            action = await session.get(JournalAction, config.command.action_id)
            assert action is not None
            actual = ActionProposal.model_validate_json(action.proposal_json)
            assert actual == config.action and action_hash(actual) == action.proposal_hash
            params = require_notification_command(
                config.registration.value.registration.sender,
                actual,
                config.command,
                config.preparation_policy.resource_symbol,
            )
            require_issued_binding(work, actual, params, intent, slot)
            observations = tuple(
                (
                    await session.scalars(
                        select(NotificationObservationRow).where(
                            NotificationObservationRow.company_id == config.command.company_id,
                            NotificationObservationRow.draft_id == config.selection.draft_id,
                        )
                    )
                ).all()
            )
            heads = tuple(
                (
                    await session.scalars(
                        select(BrainSourceHead)
                        .where(BrainSourceHead.company_id == config.command.company_id)
                        .order_by(BrainSourceHead.source_id)
                    )
                ).all()
            )
            count = await session.scalar(select(func.count()).select_from(ExecutionAttempt))
            sdk = await session.scalar(
                text("SELECT status FROM dbos.workflow_status WHERE workflow_uuid=:id"),
                {"id": config.command.workflow_id},
            )
            now = await db_now(session)
            witness.require_time(now)
            return {
                "db_now": now.isoformat(),
                "intent_state": intent.state,
                "intent_fence": intent.intent_fence,
                "receipt_json": intent.receipt_json,
                "approval_sha256": hashlib.sha256(action.approval_json.encode()).hexdigest()
                if action.approval_json
                else None,
                "source_heads": [
                    {
                        name: getattr(h, name).isoformat()
                        if isinstance(getattr(h, name), datetime)
                        else str(getattr(h, name))
                        for name in (
                            "source_id",
                            "current_revision_id",
                            "generation",
                            "observed_at",
                            "fresh_until",
                            "availability",
                        )
                    }
                    for h in heads
                ],
                "slot_sha256": hashlib.sha256(
                    json.dumps(
                        {c.name: getattr(slot, c.name) for c in slot.__table__.columns},
                        sort_keys=True,
                        default=str,
                    ).encode()
                ).hexdigest(),
                "observation_hashes": [x.record_sha256 for x in observations],
                "attempts": count,
                "model": work.model_requests_used,
                "tool": work.tool_attempts_used,
                "fence": work.fence,
                "worker_id": str(work.worker_id) if work.worker_id else None,
                "lease_until": work.lease_until.isoformat() if work.lease_until else None,
                "segment_id": str(work.segment_id),
                "hold": [
                    str(hold.amount_usd),
                    str(hold.actual_usd) if hold.actual_usd is not None else None,
                    hold.state,
                ],
                "sdk_status": sdk,
            }
    finally:
        await engine.dispose()


@dataclass(frozen=True)
class NotificationProcessRuntime:
    services: NotificationDispatchWorkerServices
    http_calls: list[str]
    blobs: ProtectedBlobStore
    drafts: QualifiedNotificationDraftStore
    sql_guard: HistoricalSQLBodyGuard | None


def compose_notification_process_services(
    factory: async_sessionmaker[AsyncSession],
    config: NotificationProcessConfig,
    opaque_credentials: OpaqueCredentialProvider,
    worker_id: UUID,
    barrier: NotificationBarrier | None,
) -> NotificationProcessRuntime:
    """Reconstruct hashes/current verifier, never a caller permit or refreshed registration."""
    # Cohesive process composition: exact catalog/root/factory dependencies and
    # trusted instrumentation must be identical for the fixed nonretry procedure.
    require_notification_process_root(config.database, config.root, existing=True)
    bind = factory.kw.get("bind")
    if not isinstance(bind, AsyncEngine):
        raise ValueError("Notification process business engine is unavailable")
    if barrier not in (None, config.barrier):
        raise ValueError("Notification process barrier differs from its case")
    registration = FileNotificationWorkerRegistration(
        config.root / "synthetic-tick-registration.json"
    )
    assert registration.snapshot() == config.registration
    recipient = config.root / "synthetic-worker-recipient.json"
    assert hashlib.sha256(recipient.read_bytes()).hexdigest() == config.recipient_file_sha256
    identities = NotificationWorkerIdentities(opaque_credentials, SecretStr(TEST_KEY), enabled=True)
    blobs = (
        ProtectedBlobStore(config.root / "blobs", storage_symbol="fixture.blobs.v1")
        if barrier
        else HistoricalOnlyBlobs(config.root / "blobs", storage_symbol="fixture.blobs.v1")
    )
    artifacts = BoundedArtifactReader(factory, blobs)
    freshness = RegisteredSourceFreshness(factory, Policies())
    fact_scheduler = SchedulerServices(
        SchedulerPolicy(
            recipe_version="tick-facts-v1",
            max_tasks=1,
            workflows=(
                WorkflowRegistration(
                    workflow_name="internal.owner-notification",
                    workflow_version="v1",
                    queue_name="tick.fixture",
                    application_name="tick-native-fixture",
                ),
            ),
        ),
        config.catalog,
        artifacts,
        freshness,
        FixtureIdentities(),
        FixtureResources(),
    )
    facts = NativeFactServices(
        config.catalog,
        artifacts,
        freshness,
        fact_scheduler,
        config.registration.value.registration.subjects[0].resource,
    )
    draft_type = QualifiedNotificationDraftStore if barrier else HistoricalOnlyDrafts
    drafts = draft_type(
        factory,
        QualifiedNotificationFactAdapter(
            NativeNotificationFactLoader(config.catalog, artifacts, freshness),
            NativeFactReader(facts),
        ),
        FileOwnerRecipients(recipient),
        policy=config.notification_policy,
    )
    preparation = ManagedNotificationPreparation(
        factory, drafts, config.catalog, artifacts, freshness, policy=config.preparation_policy
    )
    reads = NotificationWorkerServices(
        factory, identities, registration, facts, drafts, preparation
    )
    reads.require_registration(config.registration)
    effects = InstrumentedNotificationEffects(
        factory, drafts, config.catalog, artifacts, freshness, policy=config.preparation_policy
    )
    observation = NotificationProcessBarrier(config.root, barrier)
    effects.barrier = observation
    calls: list[str] = []
    raw = json.dumps({"id": str(config.response_uuid)}, separators=(",", ":")).encode()

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        append_process_marker(
            config.root,
            "http-transcript.jsonl",
            {
                "pid": os.getpid(),
                "worker_id": str(worker_id),
                "method": request.method,
                "path": request.url.path,
                "idempotency_key": request.headers.get("Idempotency-Key"),
                "body_sha256": hashlib.sha256(request.content).hexdigest(),
                "response_sha256": hashlib.sha256(raw).hexdigest(),
            },
        )
        assert (
            barrier is not None
            and request.method == "POST"
            and request.url.path == "/emails"
            and len(calls) == 1
        )
        return httpx.Response(200, content=raw)

    dispatcher = InstrumentedNotificationDispatcher(
        factory,
        drafts,
        effects,
        enabled=True,
        configuration=NotificationTransportConfiguration(
            enabled=True,
            api_key=SecretStr("synthetic-notification-process-only"),
            http_transport=httpx.MockTransport(respond),
        ),
    )
    dispatcher.barrier = observation
    execution = ExecutionStore(
        factory,
        management_catalog=config.catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
    )
    scheduler = SchedulerServices(
        SchedulerPolicy(
            recipe_version="notification-dispatch-v1",
            max_tasks=1,
            workflows=(notification_workflow_registration(),),
        ),
        config.catalog,
        artifacts,
        freshness,
        fact_scheduler.identities,
        fact_scheduler.resources,
    )
    services = NotificationDispatchWorkerServices(
        reads,
        execution,
        dispatcher,
        scheduler,
        worker_id,
        lease_ttl_seconds=config.lease_ttl_seconds,
        enabled=True,
    )
    guard = HistoricalSQLBodyGuard() if barrier is None else None
    if guard is not None:
        event.listen(bind.sync_engine, "before_cursor_execute", guard.before_cursor_execute)
    return NotificationProcessRuntime(services, calls, blobs, drafts, guard)
