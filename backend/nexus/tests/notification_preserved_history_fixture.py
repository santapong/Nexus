"""TEST-only existing issued-history context; no schema setup, private bodies or teardown."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.access_models import BrainResource
from nexus.company.brain.native_fact_contracts import DecisionSelector
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.native_profile_admission import ledger_scope
from nexus.company.management.scheduling_contracts import SchedulerPolicy
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.dispatch_store import NotificationTransportConfiguration
from nexus.company.notifications.managed_contracts import NativeNotificationSelection
from nexus.company.notifications.managed_effects import ManagedNotificationEffectStore
from nexus.company.notifications.recipient_registry import FileOwnerRecipients
from nexus.company.notifications.worker_config import FileNotificationWorkerRegistration
from nexus.company.notifications.worker_dispatch import AuthenticatedManagedNotificationDispatcher
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.execution.notification_dispatch_read import (
    require_issued_binding,
    require_notification_command,
)
from nexus.execution.notification_worker_services import (
    NotificationDispatchWorkerServices,
    notification_workflow_registration,
)
from nexus.execution.runtime_models import EffectIntent
from nexus.execution.runtime_store import ExecutionStore
from nexus.execution.runtime_support import db_now, execution_row, runtime_transaction
from nexus.harness.journal_models import JournalAction
from nexus.tests.notification_durable_pg_fixture import (
    DurableNotificationCase,
    qualified_durable_url,
)
from nexus.tests.notification_preserved_history_support import (
    ORIGINAL_ROOT,
    HistoricalOnlyBlobs,
    HistoricalOnlyDrafts,
    HistoricalSQLBodyGuard,
    historical_reads,
    new_historical_identities,
    retained_command,
)
from nexus.tests.notification_worker_enqueue_pg_fixture import (
    AtomicNotificationCase,
    AtomicNotificationDatabases,
)
from nexus.tests.notification_worker_tick_declarations import tick_catalog


@dataclass(frozen=True)
class PreservedNotificationCase:
    databases: AtomicNotificationDatabases
    case: DurableNotificationCase
    command: SegmentCommand
    blobs: HistoricalOnlyBlobs
    drafts: HistoricalOnlyDrafts
    http_attempts: list[str]
    original_credential_expires_at: datetime
    actual_audit_db_clock: datetime
    original_registration_sha256: str
    original_decision_sha256: str
    original_recipient_sha256: str
    original_recipient_registered_at: datetime
    original_recipient_expires_at: datetime
    sql_guard: HistoricalSQLBodyGuard
    original_receipt_sha256: str = (
        "1f97db96b0790d19071006bb2cafb2d1ef5a6a3445811c61e67dfec32e5c419f"
    )
    original_observation_sha256: str = (
        "83f156f0ddf234f67841882b9d9838a74e8880aca6e42e376cc06faddb8bce6e"
    )


@asynccontextmanager
async def preserved_notification_case() -> AsyncIterator[PreservedNotificationCase]:
    """One newly approved current synthetic historical witness; only existing exact issued basis."""
    # Cohesive fixture exception: actual member/issued basis and reconstructed
    # original hash-bound readers share one old DB and no source/approval/setup mutation.
    url = qualified_durable_url()
    retained = retained_command()
    command, old_expiry, requests = (
        retained.command,
        retained.original_credential_expires_at,
        retained.requests,
    )
    registration = FileNotificationWorkerRegistration(
        ORIGINAL_ROOT / "synthetic-tick-registration.json"
    )
    snapshot = registration.snapshot()
    assert snapshot.sha256 == retained.registration_sha256
    assert snapshot.value.registration.sender.company_id == command.company_id
    identities = new_historical_identities(snapshot)
    witness = await identities.current(expected_binding=snapshot.value.registration.sender)
    scope = ledger_scope(snapshot.value.registration.sender)
    http_attempts: list[str] = []
    app = create_async_engine(url.set(username="nexus_company_app"), poolclass=NullPool)
    admin = create_async_engine(url, poolclass=NullPool)
    sql_guard = HistoricalSQLBodyGuard()
    event.listen(app.sync_engine, "before_cursor_execute", sql_guard.before_cursor_execute)
    factory = async_sessionmaker(app, expire_on_commit=False)

    def deny_http(request: httpx.Request) -> httpx.Response:
        http_attempts.append(request.method)
        raise AssertionError("Historical-only continuation cannot invoke HTTP")

    try:
        async with runtime_transaction(
            factory, scope, witness.identity, allow_paused=True, allow_inactive=True
        ) as (session, control, _):
            assert control.owner_id == witness.identity.principal_id
            assert await session.scalar(text("SELECT current_user")) == "nexus_company_app"
            assert await session.scalar(text("SELECT current_database()")) == url.database
            assert (
                await session.scalar(
                    text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
                )
                is False
            )
            work = await execution_row(session, scope)
            action = await session.get(JournalAction, command.action_id)
            intent = await session.get(EffectIntent, (command.company_id, command.action_id))
            assert action is not None and action.approval_json is not None and intent is not None
            assert (
                hashlib.sha256(action.approval_json.encode()).hexdigest()
                == retained.decision_sha256
            )
            assert intent.state == "succeeded" and intent.receipt_json is not None
            proposal = ActionProposal.model_validate_json(action.proposal_json)
            params = require_notification_command(
                snapshot.value.registration.sender, proposal, command, "owner.notifications"
            )
            slot = await session.get(NotificationDispatchRow, (command.company_id, params.draft_id))
            assert slot is not None
            require_issued_binding(work, proposal, params, intent, slot)
            policies = (
                FileOwnerRecipients(ORIGINAL_ROOT / "synthetic-worker-recipient.json")
                ._read()
                .policies
            )
            assert len(policies) == 1
            recipient = policies[0]
            assert (recipient.company_id, recipient.owner_id) == (
                command.company_id,
                command.actor_id,
            )
            assert recipient.sha256 == slot.recipient_policy_sha256
            targets = tuple(
                (
                    await session.scalars(
                        select(BrainResource.resource_id)
                        .where(
                            BrainResource.company_id == command.company_id,
                            BrainResource.kind == "artifact",
                        )
                        .limit(2)
                    )
                ).all()
            )
            assert len(targets) == 1
            catalog = tick_catalog(
                ResourceRef(company_id=command.company_id, resource_id=targets[0])
            )
            assert canonical_sha256(catalog) == snapshot.value.registration.catalog_sha256
            actual_clock = await db_now(session)
            assert old_expiry <= actual_clock
            witness.require_time(actual_clock)
            assert (
                snapshot.value.registration.registered_at
                <= actual_clock
                < snapshot.value.registration.expires_at
            )
        reads, blobs, drafts = historical_reads(
            factory, catalog, identities, registration, snapshot
        )
        facts = reads.facts
        effects = ManagedNotificationEffectStore(
            factory,
            drafts,
            catalog,
            facts.artifacts,
            facts.freshness,
            policy=reads.preparation.policy,
        )
        dispatcher = AuthenticatedManagedNotificationDispatcher(
            factory,
            drafts,
            effects,
            enabled=True,
            configuration=NotificationTransportConfiguration(
                enabled=True,
                api_key=SecretStr("synthetic-history-no-http"),
                http_transport=httpx.MockTransport(deny_http),
            ),
        )
        execution = ExecutionStore(
            factory,
            management_catalog=catalog,
            management_artifacts=facts.artifacts,
            management_freshness=facts.freshness,
        )
        scheduler = SchedulerServices(
            SchedulerPolicy(
                recipe_version="notification-dispatch-v1",
                max_tasks=1,
                workflows=(notification_workflow_registration(),),
            ),
            catalog,
            facts.artifacts,
            facts.freshness,
            facts.scheduler.identities,
            facts.scheduler.resources,
        )
        services = NotificationDispatchWorkerServices(
            reads, execution, dispatcher, scheduler, worker_id=uuid4(), enabled=True
        )
        assert isinstance(snapshot.value.registration.subjects[0].selector, DecisionSelector)
        source_action_id = snapshot.value.registration.subjects[0].selector.action_id
        atomic = AtomicNotificationCase(
            services,
            NativeNotificationSelection(
                company_id=command.company_id,
                draft_id=params.draft_id,
                sender_task_id=command.task_id,
                plan=snapshot.value.registration.plan,
            ),
            witness,
            snapshot,
            source_action_id,
            hashlib.sha256(action.approval_json.encode()).hexdigest(),
            [],
        )
        yield PreservedNotificationCase(
            AtomicNotificationDatabases(factory, async_sessionmaker(admin, expire_on_commit=False)),
            DurableNotificationCase(atomic, requests),
            command,
            blobs,
            drafts,
            http_attempts,
            old_expiry,
            actual_clock,
            retained.registration_sha256,
            retained.decision_sha256,
            recipient.sha256,
            recipient.registered_at,
            recipient.expires_at,
            sql_guard,
        )
    finally:
        event.remove(app.sync_engine, "before_cursor_execute", sql_guard.before_cursor_execute)
        await app.dispose()
        await admin.dispose()
