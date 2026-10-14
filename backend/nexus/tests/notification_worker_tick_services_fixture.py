"""TEST-only actual service composition, immutable synthetic registration and signed test token."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import jwt
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.access_contracts import ResourceRef
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.native_fact_contracts import DecisionSelector
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.plan_support import CurrentPlanBinding
from nexus.company.management.scheduling_contracts import SchedulerPolicy, WorkflowRegistration
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.contracts import NotificationPolicy
from nexus.company.notifications.managed_contracts import NotificationPreparationPolicy
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.company.notifications.native_loader import NativeNotificationFactLoader
from nexus.company.notifications.qualified_adapter import QualifiedNotificationFactAdapter
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.company.notifications.worker_config import FileNotificationWorkerRegistration
from nexus.company.notifications.worker_contracts import (
    NotificationWorkerConfiguration,
    NotificationWorkerRegistration,
    NotificationWorkerRegistrationFile,
    WorkerSubject,
)
from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.company.notifications.worker_services import NotificationWorkerServices
from nexus.tests.integration.management_acceptance_source_fixture import Policies
from nexus.tests.integration.test_company_brain_ingestion import RESOURCE
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_scheduler_support import FixtureIdentities, FixtureResources
from nexus.tests.notification_worker_credential_fixture import TEST_KEY, recipient_file
from nexus.tests.notification_worker_tick_declarations import TARGET_SYMBOL
from nexus.tests.notification_worker_tick_fixture import WorkerTickNativeCase


class SyntheticTickCredential:
    """No production issuance path; one static public-test-key token only."""

    def __init__(self, value: SecretStr) -> None:
        self._value = value

    async def credential(self) -> SecretStr:
        return self._value


def synthetic_tick_identities(
    case: WorkerTickNativeCase, *, seconds: int = 60
) -> NotificationWorkerIdentities:
    sender = case.notification.children[0].binding
    now = int(datetime.now(UTC).timestamp())
    value = jwt.encode(
        {
            "sub": str(sender.actor_id),
            "workspace_id": str(sender.workspace_id),
            "iat": now - 1,
            "exp": now + seconds,
        },
        TEST_KEY,
        algorithm="HS256",
    )
    return NotificationWorkerIdentities(
        SyntheticTickCredential(SecretStr(value)),
        SecretStr(TEST_KEY),
        enabled=True,
    )


def native_tick_facts(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    case: WorkerTickNativeCase,
) -> NativeFactServices:
    artifacts = BoundedArtifactReader(
        factory, ProtectedBlobStore(root, storage_symbol="fixture.blobs.v1")
    )
    freshness = RegisteredSourceFreshness(factory, Policies())
    scheduler = SchedulerServices(
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
        case.catalog,
        artifacts,
        freshness,
        FixtureIdentities(),
        FixtureResources(),
    )
    return NativeFactServices(
        case.catalog,
        artifacts,
        freshness,
        scheduler,
        ResourceRef(company_id=COMPANY, resource_id=RESOURCE),
    )


async def configured_tick_services(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    case: WorkerTickNativeCase,
) -> NotificationWorkerServices:
    facts = native_tick_facts(factory, root / "blobs", case)
    reader = NativeFactReader(facts)
    drafts = QualifiedNotificationDraftStore(
        factory,
        QualifiedNotificationFactAdapter(
            NativeNotificationFactLoader(case.catalog, facts.artifacts, facts.freshness), reader
        ),
        recipient_file(root),
        policy=NotificationPolicy(enabled=True),
    )
    preparation = ManagedNotificationPreparation(
        factory,
        drafts,
        case.catalog,
        facts.artifacts,
        facts.freshness,
        policy=NotificationPreparationPolicy(
            enabled=True,
            target=case.catalog.notification_profiles[0].target_resource,
            resource_symbol=TARGET_SYMBOL,
        ),
    )
    sender = case.notification.children[0].binding
    async with management_owner_transaction(factory, control(), identity(OWNER)) as (session, _, _):
        bound = await ManagementPlanStore.current_binding(session, COMPANY, sender.task_id)
        assert bound is not None
    return NotificationWorkerServices(
        factory,
        synthetic_tick_identities(case),
        registration_file(root, case, facts, drafts, preparation, bound),
        facts,
        drafts,
        preparation,
    )


def registration_file(
    root: Path,
    case: WorkerTickNativeCase,
    facts: NativeFactServices,
    drafts: QualifiedNotificationDraftStore,
    preparation: ManagedNotificationPreparation,
    bound: CurrentPlanBinding,
) -> FileNotificationWorkerRegistration:
    sender = case.notification.children[0].binding
    now = datetime.now(UTC)
    registration = NotificationWorkerRegistration(
        company_id=COMPANY,
        workspace_id=sender.workspace_id,
        registration_id=uuid4(),
        sender=sender,
        plan=bound.plan,
        catalog_sha256=canonical_sha256(case.catalog),
        notification_policy_sha256=canonical_sha256(drafts.policy),
        preparation_policy_sha256=canonical_sha256(preparation.policy),
        registered_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        subjects=(
            WorkerSubject(
                selector=DecisionSelector(
                    company_id=COMPANY, action_id=case.source_action.action_id
                ),
                resource=facts.resource,
            ),
        ),
    )
    path = root / "synthetic-tick-registration.json"
    path.write_text(
        NotificationWorkerRegistrationFile(
            registration=registration,
            configuration=NotificationWorkerConfiguration(
                enabled=True,
                emit_fallback=True,
                consume_events=True,
                prepare_pending=True,
            ),
        ).model_dump_json()
    )
    path.chmod(0o600)
    return FileNotificationWorkerRegistration(path)
