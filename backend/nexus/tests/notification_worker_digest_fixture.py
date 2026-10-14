"""TEST-only protected owner snapshot with a real native edge and empty-model digest config."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.native_fact_contracts import DigestSelector, RegisteredDigestPolicy
from nexus.company.brain.native_fact_digest import digest_window
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.sources import ArtifactRevisionRef
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.operating_report_contracts import SavedOperatingReport
from nexus.company.management.operating_report_inputs import author_input_references
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.plan_store import ManagementPlanStore
from nexus.company.management.transactions import management_owner_transaction
from nexus.company.notifications.contracts import NotificationPolicy
from nexus.company.notifications.draft_store import owner_scope
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.company.notifications.native_loader import NativeNotificationFactLoader
from nexus.company.notifications.qualified_adapter import QualifiedNotificationFactAdapter
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.company.notifications.worker_contracts import (
    NotificationWorkerRegistrationFile,
    WorkerSubject,
)
from nexus.company.notifications.worker_services import NotificationWorkerServices
from nexus.execution.runtime_support import db_now
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.notification_worker_digest_observations import (
    digest_native_counts as digest_native_counts,
)
from nexus.tests.notification_worker_digest_observations import (
    require_digest_pins as require_digest_pins,
)
from nexus.tests.notification_worker_tick_fixture import (
    WorkerTickNativeCase,
    worker_tick_native_case,
)
from nexus.tests.notification_worker_tick_services_fixture import configured_tick_services


@dataclass(frozen=True)
class WorkerDigestCase:
    native: WorkerTickNativeCase
    services: NotificationWorkerServices
    saved: SavedOperatingReport
    registration: RegisteredDigestPolicy
    baseline_references: tuple[ArtifactRevisionRef, ...]
    clock_observed: datetime
    window: tuple[str, datetime] | None


async def save_native_owner_report(
    services: NotificationWorkerServices,
    case: WorkerTickNativeCase,
) -> tuple[SavedOperatingReport, tuple[ArtifactRevisionRef, ...], datetime]:
    author = case.source.children[0].binding
    async with management_owner_transaction(services.factory, control(), identity(OWNER)) as (
        session,
        _,
        _,
    ):
        bound = await ManagementPlanStore.current_binding(session, COMPANY, author.task_id)
        assert bound is not None and bound.child.binding == author
        now = await db_now(session)
    facts = services.facts
    reports = OperatingReportStore(
        services.factory, facts.catalog, facts.artifacts, facts.freshness
    )
    saved = await reports.save_snapshot(
        control(),
        identity(OWNER),
        bound.plan.plan_revision_id,
        author.task_id,
        (),
        period_start=now - timedelta(days=1),
        period_end=now,
    )
    assert await reports.get_saved(control(), identity(OWNER), saved.report_id) == saved
    assert saved.selection.author == case.source.children[0].binding
    assert saved.selection.verifier == case.source.children[1].binding
    assert saved.selection.author.actor_id != saved.selection.verifier.actor_id
    assert saved.created_by == OWNER and saved.data.source_heads
    assert not saved.selection.work and not saved.data.work and not saved.data.charges
    assert saved.projection.accepted_task_ids == saved.projection.receipt_task_ids == ()
    async with management_owner_transaction(services.factory, control(), identity(OWNER)) as (
        session,
        actual,
        _,
    ):
        references = await author_input_references(
            session,
            actual,
            owner_scope(control(), identity(OWNER)),
            identity(OWNER),
            saved,
            facts.artifacts,
            facts.freshness,
        )
        assert references and saved.data.required_resource_ids
        observed = await db_now(session)
    return saved, references, observed


def digest_services(
    original: NotificationWorkerServices,
    registration: RegisteredDigestPolicy,
) -> NotificationWorkerServices:
    facts = replace(original.facts, digests=(registration,))
    reader = NativeFactReader(facts)
    drafts = QualifiedNotificationDraftStore(
        original.factory,
        QualifiedNotificationFactAdapter(
            NativeNotificationFactLoader(facts.catalog, facts.artifacts, facts.freshness), reader
        ),
        original.drafts.recipients,
        policy=registration.policy,
    )
    preparation = ManagedNotificationPreparation(
        original.factory,
        drafts,
        facts.catalog,
        facts.artifacts,
        facts.freshness,
        policy=original.preparation.policy,
    )
    return NotificationWorkerServices(
        original.factory,
        original.identities,
        original.registrations,
        facts,
        drafts,
        preparation,
    )


def configure_digest_subject(
    root: Path, services: NotificationWorkerServices, registration: RegisteredDigestPolicy
) -> None:
    path = root / "synthetic-tick-registration.json"
    previous = NotificationWorkerRegistrationFile.model_validate_json(path.read_bytes())
    pinned = previous.registration.model_copy(
        update={
            "notification_policy_sha256": canonical_sha256(services.drafts.policy),
            "subjects": (
                WorkerSubject(
                    selector=DigestSelector(company_id=COMPANY, schedule=registration.schedule),
                    resource=registration.resource,
                ),
            ),
        }
    )
    value = NotificationWorkerRegistrationFile.model_validate_json(
        previous.model_copy(update={"registration": pinned}).model_dump_json()
    )
    assert (value.registration.sender, value.registration.plan) == (
        previous.registration.sender,
        previous.registration.plan,
    )
    path.write_text(value.model_dump_json())
    path.chmod(0o600)
    services.require_registration(services.registrations.snapshot())


async def worker_digest_case(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    kind: Literal["daily", "weekly"],
) -> WorkerDigestCase:
    native = await worker_tick_native_case(factory, root / "blobs")
    original = await configured_tick_services(factory, root, native)
    saved, references, now = await save_native_owner_report(original, native)
    registration = RegisteredDigestPolicy(
        company_id=COMPANY,
        schedule=f"worker-protected-{kind}-v1",
        kind=kind,
        report_id=saved.report_id,
        policy=NotificationPolicy(
            enabled=True, daily_digest=kind == "daily", weekly_digest=kind == "weekly"
        ),
        resource=original.preparation.policy.target,
        registered_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    services = digest_services(original, registration)
    configure_digest_subject(root, services, registration)
    return WorkerDigestCase(
        native, services, saved, registration, references, now, digest_window(kind, now)
    )
