"""TEST-only closed retained metadata and no-body service composition; no company mutations."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import jwt
from pydantic import SecretStr
from sqlalchemy import Connection
from sqlalchemy.engine import ExecutionContext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.blob_store import ProtectedBlobStore
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.plan_support import PlanAdmissionCatalog
from nexus.company.management.scheduling_contracts import SchedulerPolicy, WorkflowRegistration
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.company.notifications.contracts import NotificationDraft, NotificationPolicy
from nexus.company.notifications.managed_contracts import NotificationPreparationPolicy
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.company.notifications.native_loader import NativeNotificationFactLoader
from nexus.company.notifications.qualified_adapter import QualifiedNotificationFactAdapter
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.company.notifications.recipient_registry import FileOwnerRecipients
from nexus.company.notifications.worker_config import (
    FileNotificationWorkerRegistration,
    WorkerRegistrationSnapshot,
)
from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.company.notifications.worker_services import NotificationWorkerServices
from nexus.execution.dbos_contracts import SegmentCommand
from nexus.harness.journal_models import CompanyControl
from nexus.tests.integration.management_acceptance_source_fixture import Policies
from nexus.tests.management_scheduler_support import FixtureIdentities, FixtureResources
from nexus.tests.notification_durable_pg_fixture import MockNotificationRequest
from nexus.tests.notification_worker_credential_fixture import TEST_KEY
from nexus.tests.notification_worker_tick_declarations import TARGET_SYMBOL
from nexus.tests.notification_worker_tick_services_fixture import SyntheticTickCredential

ORIGINAL_ROOT = Path(
    "/home/santapong/.codex/nexus-local-release-fixtures-20261014-continued/notification-durable-first-pg-20261015-1/pytest/test_actual_sdk_one_mock_post_0"
)
_PHASE_SHA = "87a6100902fa0edfd0ebaee0bcad4124f169c7f3dd10adb1681487aad0d01ca2"
_TRANSCRIPT_SHA = "47a4ae4fea31b78dcb6c11cc0f8d7b0bc722c57c5d13a2aacdf11a27eb34e346"


@dataclass(frozen=True)
class RetainedMetadata:
    command: SegmentCommand
    original_credential_expires_at: datetime
    requests: list[MockNotificationRequest]
    registration_sha256: str
    decision_sha256: str


@dataclass
class HistoricalSQLBodyGuard:
    checked: int = 0
    body_sql_attempts: int = 0

    def inspect_sql(self, statement: str) -> None:
        """Deny selected private draft fields, including direct full-row/CTE reads; log no SQL."""
        self.checked += 1
        lowered = statement.lower()
        if (
            "company_notification_drafts" in lowered
            and re.search(r"\bselect\b", lowered)
            and (
                re.search(r"\b(payload_json|record_json)\b", lowered)
                or re.search(r"\bselect\s+(?:\w+\.)?\*", lowered)
            )
        ):
            self.body_sql_attempts += 1
            raise AssertionError("Historical replay cannot select a private draft body")

    def before_cursor_execute(
        self,
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        self.inspect_sql(statement)


def retained_command() -> RetainedMetadata:
    """Read exact retained metadata/transcript bytes only; never the private blob namespace."""
    raw = (ORIGINAL_ROOT / "durable-phase-proof.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _PHASE_SHA
    value = json.loads(raw)
    command = SegmentCommand.model_validate(value["command"])
    original_expiry = datetime.fromisoformat(value["window"]["credential_expires_at"])
    registration_sha = value["window"]["worker_registration_file_sha256"]
    decision_sha = value["before"]["decision_sha256"]
    assert isinstance(registration_sha, str) and isinstance(decision_sha, str)
    transcript = (ORIGINAL_ROOT / "mock-http-transcript.jsonl").read_bytes()
    assert hashlib.sha256(transcript).hexdigest() == _TRANSCRIPT_SHA
    requests = [MockNotificationRequest.model_validate_json(x) for x in transcript.splitlines()]
    assert len(requests) == 1 and requests[0].method == "POST"
    return RetainedMetadata(command, original_expiry, requests, registration_sha, decision_sha)


class HistoricalOnlyBlobs(ProtectedBlobStore):
    reads: int = 0
    writes: int = 0

    async def read(self, artifact: ArtifactRevisionRef) -> bytes:
        self.reads += 1
        raise AssertionError("Historical replay cannot read a private blob")

    async def save(self, artifact: ArtifactRevisionRef, raw: bytes) -> None:
        self.writes += 1
        raise AssertionError("Historical replay cannot write a private blob")


class HistoricalOnlyDrafts(QualifiedNotificationDraftStore):
    body_reads: int = 0

    async def get_current(
        self, scope: CompanyControlScope, identity: VerifiedIdentity, draft_id: UUID
    ) -> NotificationDraft | None:
        self.body_reads += 1
        raise AssertionError("Historical replay cannot disclose a draft body")

    async def get_current_locked(
        self,
        session: AsyncSession,
        control: CompanyControl,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        draft_id: UUID,
    ) -> NotificationDraft | None:
        self.body_reads += 1
        raise AssertionError("Historical replay cannot disclose a draft body")


def new_historical_identities(snapshot: WorkerRegistrationSnapshot) -> NotificationWorkerIdentities:
    """Root authorized this NEW synthetic historical token; original token is never refreshed."""
    sender = snapshot.value.registration.sender
    now = int(datetime.now(UTC).timestamp())
    value = jwt.encode(
        {
            "sub": str(sender.actor_id),
            "workspace_id": str(sender.workspace_id),
            "iat": now - 1,
            "exp": now + 120,
        },
        TEST_KEY,
        algorithm="HS256",
    )
    return NotificationWorkerIdentities(
        SyntheticTickCredential(SecretStr(value)), SecretStr(TEST_KEY), enabled=True
    )


def historical_reads(
    factory: async_sessionmaker[AsyncSession],
    catalog: PlanAdmissionCatalog,
    identities: NotificationWorkerIdentities,
    registration: FileNotificationWorkerRegistration,
    snapshot: WorkerRegistrationSnapshot,
) -> tuple[NotificationWorkerServices, HistoricalOnlyBlobs, HistoricalOnlyDrafts]:
    """Reconstruct exact declared policies/readers without source/plan/config writes or ticking."""
    # Cohesive pure composition: same existing catalog/root/policy dependencies
    # must share one factory and remain hash-bound to the original file.
    blobs = HistoricalOnlyBlobs(ORIGINAL_ROOT / "blobs", storage_symbol="fixture.blobs.v1")
    artifacts = BoundedArtifactReader(factory, blobs)
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
        catalog,
        artifacts,
        freshness,
        FixtureIdentities(),
        FixtureResources(),
    )
    subjects = snapshot.value.registration.subjects
    assert len(subjects) == 1
    facts = NativeFactServices(catalog, artifacts, freshness, scheduler, subjects[0].resource)
    drafts = HistoricalOnlyDrafts(
        factory,
        QualifiedNotificationFactAdapter(
            NativeNotificationFactLoader(catalog, artifacts, freshness), NativeFactReader(facts)
        ),
        FileOwnerRecipients(ORIGINAL_ROOT / "synthetic-worker-recipient.json"),
        policy=NotificationPolicy(enabled=True),
    )
    preparation = ManagedNotificationPreparation(
        factory,
        drafts,
        catalog,
        artifacts,
        freshness,
        policy=NotificationPreparationPolicy(
            enabled=True,
            target=catalog.notification_profiles[0].target_resource,
            resource_symbol=TARGET_SYMBOL,
        ),
    )
    reads = NotificationWorkerServices(
        factory, identities, registration, facts, drafts, preparation
    )
    reads.require_registration(snapshot)
    assert canonical_sha256(catalog) == snapshot.value.registration.catalog_sha256
    return reads, blobs, drafts
