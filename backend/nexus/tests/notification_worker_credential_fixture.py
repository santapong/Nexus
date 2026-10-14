"""Exclusive normal015 empty-model native source/draft/sender and synthetic credential fixture."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.company.brain.native_fact_contracts import DecisionSelector
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.contracts.actions import ActionProposal
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plans import RunBinding
from nexus.company.management.scheduling_contracts import SchedulerPolicy, WorkflowRegistration
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.contracts import NotificationPolicy, OwnerRecipientPolicy
from nexus.company.notifications.dispatch_models import NotificationDispatchRow
from nexus.company.notifications.dispatch_store import NotificationTransportConfiguration
from nexus.company.notifications.managed_contracts import (
    NativeNotificationSelection,
    NotificationPreparationPolicy,
    PreparedNotification,
)
from nexus.company.notifications.managed_effects import ManagedNotificationEffectStore
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.company.notifications.native_loader import NativeNotificationFactLoader
from nexus.company.notifications.qualified_adapter import QualifiedNotificationFactAdapter
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.company.notifications.recipient_registry import (
    FileOwnerRecipients,
    RecipientRegistryFile,
)
from nexus.company.notifications.worker_dispatch import AuthenticatedManagedNotificationDispatcher
from nexus.company.notifications.worker_identity import (
    AuthenticatedWorkerIdentity,
    NotificationWorkerIdentities,
)
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.execution.runtime_models import EffectIntent, ExecutionWork
from nexus.execution.runtime_support import runtime_transaction
from nexus.harness.canonical import action_hash
from nexus.harness.journal import CompanyJournal
from nexus.harness.journal_models import CostHold
from nexus.settings import settings
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control, migrate
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_scheduler_support import FixtureIdentities, FixtureResources
from nexus.tests.notification_native_profile_fixture import (
    SYMBOL,
    NotificationNativeScenario,
    notification_action,
    notification_native_scenario,
)

TEST_KEY = "notification-worker-public-synthetic-key-at-least-64-characters-long-for-tests"


@pytest.fixture
async def worker_credentials_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Only the new assigned disposable DB can be installed or reset by this fixture."""
    url = make_url(settings.company_test_database_url)
    assert url.database == "nexus_company_test_notification_worker_credentials"
    admin = create_async_engine(url)
    app = create_async_engine(url.set(username="nexus_company_app"))
    installed = False
    try:
        async with admin.begin() as connection:
            await connection.run_sync(migrate, "upgrade")
        installed = True
        yield async_sessionmaker(app, expire_on_commit=False)
    finally:
        await app.dispose()
        if installed:
            async with admin.begin() as connection:
                # Only this disposable fixture; preserve015's refusal for production histories.
                await connection.execute(text("TRUNCATE company_brain_events CASCADE"))
                await connection.run_sync(migrate, "downgrade")
        await admin.dispose()


@dataclass(frozen=True)
class WorkerCredentialCase:
    native: NotificationNativeScenario
    drafts: QualifiedNotificationDraftStore
    effects: ManagedNotificationEffectStore
    selection: NativeNotificationSelection
    prepared: PreparedNotification
    lease: ExecutionLease
    source_action: ActionProposal


@dataclass(frozen=True)
class WorkerCredentialFacts:
    intent_state: str | None
    slot_present: bool
    tool_attempts: int
    model_requests: int
    hold_state: str
    hold_amount: Decimal
    actual_usd: Decimal | None


async def credential_facts(
    factory: async_sessionmaker[AsyncSession], case: WorkerCredentialCase
) -> WorkerCredentialFacts:
    """Read actual current native histories under the same owner/work company mutex."""
    action_id = case.prepared.action.proposal.action_id
    async with runtime_transaction(
        factory, case.native.scope, identity(OWNER), allow_paused=True, allow_inactive=True
    ) as (session, _, _):
        intent = await session.get(EffectIntent, (COMPANY, action_id))
        slot = await session.get(NotificationDispatchRow, (COMPANY, case.selection.draft_id))
        work = await session.get(ExecutionWork, (COMPANY, case.native.sender.task_id))
        hold = await session.get(CostHold, action_id)
        assert work is not None and hold is not None
        return WorkerCredentialFacts(
            intent.state if intent else None,
            slot is not None,
            work.tool_attempts_used,
            work.model_requests_used,
            hold.state,
            hold.amount_usd,
            hold.actual_usd,
        )


def fact_services(native: NotificationNativeScenario) -> NativeFactServices:
    target = native.catalog.notification_profiles[0].target_resource
    registration = WorkflowRegistration(
        workflow_name="internal.owner-notification",
        workflow_version="v1",
        queue_name="credential.fixture",
        application_name="credential-native-fixture",
    )
    scheduler = SchedulerServices(
        SchedulerPolicy(
            recipe_version="credential-facts-v1", workflows=(registration,), max_tasks=1
        ),
        native.catalog,
        native.artifacts,
        native.freshness,
        FixtureIdentities(),
        FixtureResources(),
    )
    return NativeFactServices(native.catalog, native.artifacts, native.freshness, scheduler, target)


def recipient_file(root: Path) -> FileOwnerRecipients:
    now = datetime.now(UTC)
    path = root / "synthetic-worker-recipient.json"
    path.write_text(
        RecipientRegistryFile(
            policies=(
                OwnerRecipientPolicy(
                    company_id=COMPANY,
                    owner_id=OWNER,
                    policy_id=uuid4(),
                    version="credential-native-fixture-v1",
                    sender="system@example.invalid",
                    recipient="owner@example.invalid",
                    registered_at=now - timedelta(minutes=1),
                    expires_at=now + timedelta(hours=1),
                ),
            )
        ).model_dump_json()
    )
    path.chmod(0o600)
    assert path.stat().st_mode & 0o777 == 0o600
    return FileOwnerRecipients(path)


async def credential_case(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> WorkerCredentialCase:
    """A real pending source stays distinct; only the actual sender approval is consumed."""
    native, drafts, selection, source_action = await native_decision_draft(factory, root)
    policy = NotificationPreparationPolicy(
        enabled=True,
        target=native.catalog.notification_profiles[0].target_resource,
        resource_symbol=SYMBOL,
    )
    preparation = ManagedNotificationPreparation(
        factory, drafts, native.catalog, native.artifacts, native.freshness, policy=policy
    )
    effects = ManagedNotificationEffectStore(
        factory, drafts, native.catalog, native.artifacts, native.freshness, policy=policy
    )
    prepared = await preparation.prepare(control(), identity(OWNER), selection)
    assert prepared.action.proposal.action_id != source_action.action_id
    journal = CompanyJournal(factory)
    action = prepared.action.proposal
    await journal.approve_registered(
        native.scope,
        action.action_id,
        action_hash(action),
        datetime.now(UTC),
        identity=identity(OWNER),
    )
    await journal.authorize_registered(
        native.scope, action.action_id, datetime.now(UTC), (), identity=identity(OWNER)
    )
    lease = await native.runtime.claim(native.scope, identity(OWNER), uuid4(), ttl_seconds=60)
    return WorkerCredentialCase(native, drafts, effects, selection, prepared, lease, source_action)


async def native_decision_draft(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> tuple[
    NotificationNativeScenario,
    QualifiedNotificationDraftStore,
    NativeNotificationSelection,
    ActionProposal,
]:
    """Actual immutable work/source and emitter produce a currently qualified decision draft."""
    native = await notification_native_scenario(factory, root / "blobs")
    source_action = await notification_action(factory, native, approve=False)
    services = fact_services(native)
    reader = NativeFactReader(services)
    event = await NativeFactEmitter(factory, reader).emit(
        owner_scope(),
        identity(OWNER),
        DecisionSelector(company_id=COMPANY, action_id=source_action.action_id),
    )
    assert event is not None
    drafts = QualifiedNotificationDraftStore(
        factory,
        QualifiedNotificationFactAdapter(
            NativeNotificationFactLoader(native.catalog, native.artifacts, native.freshness), reader
        ),
        recipient_file(root),
        policy=NotificationPolicy(enabled=True),
    )
    draft = await drafts.publish_event(control(), identity(OWNER), event.event_id)
    async with management_owner_transaction(factory, control(), identity(OWNER)) as (session, _, _):
        bound = await ManagementPlanStore.current_binding(session, COMPANY, native.sender.task_id)
    assert bound is not None
    selection = NativeNotificationSelection(
        company_id=COMPANY,
        draft_id=draft.draft_id,
        sender_task_id=native.sender.task_id,
        plan=bound.plan,
    )
    return native, drafts, selection, source_action


class FixtureCredential:
    def __init__(self, token: str) -> None:
        self.token = SecretStr(token)

    async def credential(self) -> SecretStr:
        return self.token


async def worker_witness(binding: RunBinding, *, seconds: int = 60) -> AuthenticatedWorkerIdentity:
    """Only a synthetic test token is issued; no credential is stored or automatically renewed."""
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {
            "sub": str(binding.actor_id),
            "workspace_id": str(binding.workspace_id),
            "iat": now - 1,
            "exp": now + seconds,
        },
        TEST_KEY,
        algorithm="HS256",
    )
    return await NotificationWorkerIdentities(
        FixtureCredential(token), SecretStr(TEST_KEY), enabled=True
    ).current(binding)


def credential_dispatcher(
    factory: async_sessionmaker[AsyncSession], case: WorkerCredentialCase, calls: list[str]
) -> AuthenticatedManagedNotificationDispatcher:
    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"id": str(UUID(int=9471))})

    return AuthenticatedManagedNotificationDispatcher(
        factory,
        case.drafts,
        case.effects,
        enabled=True,
        configuration=NotificationTransportConfiguration(
            enabled=True,
            api_key=SecretStr("mock-only"),
            http_transport=httpx.MockTransport(response),
        ),
    )
