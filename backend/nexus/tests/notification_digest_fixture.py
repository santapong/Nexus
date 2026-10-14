"""Actual owner-saved reports and native digest wakes; initial sender quota is fixture only."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.native_fact_contracts import DigestSelector, RegisteredDigestPolicy
from nexus.company.brain.native_fact_emitter import NativeFactEmitter
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.scheduling_contracts import SchedulerPolicy, WorkflowRegistration
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.company.notifications.contracts import NotificationPolicy
from nexus.company.notifications.managed_effects import ManagedNotificationEffectStore
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.company.notifications.native_loader import NativeNotificationFactLoader
from nexus.company.notifications.qualified_adapter import QualifiedNotificationFactAdapter
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.tests.integration.test_company_brain_ingestion import owner_scope
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.management_scheduler_support import FixtureIdentities, FixtureResources
from nexus.tests.notification_digest_base import configured_digest_base
from nexus.tests.notification_managed_fixture import ManagedNotificationCase


async def configured_digest(
    factory: async_sessionmaker[AsyncSession],
    root: Path,
    kind: Literal["daily", "weekly"],
    *,
    report_count: int = 1,
    expires_after: float = 3600,
) -> tuple[ManagedNotificationCase, tuple[ManagedNotificationCase, ...]]:
    case = await configured_digest_base(factory, root)
    catalog, artifacts, freshness = (
        case.plans.catalog,
        case.metric.store.artifacts,
        case.metric.store.freshness,
    )
    reports = OperatingReportStore(factory, catalog, artifacts, freshness)
    now = datetime.now(UTC)
    saved = tuple(
        [
            await reports.save_snapshot(
                control(),
                identity(OWNER),
                case.selection.plan.plan_revision_id,
                case.metric.payload.children[0].binding.task_id,
                (),
                period_start=now - timedelta(days=1),
                period_end=now,
            )
            for _ in range(report_count)
        ]
    )
    policy = NotificationPolicy(
        enabled=True,
        daily_digest=True,
        weekly_digest=True,
        routine_per_day=1,
        major_completion_task_ids=case.metric.request.task_ids,
    )
    registered = tuple(
        RegisteredDigestPolicy(
            company_id=COMPANY,
            schedule=f"digest-fixture-{kind}-{index}",
            kind=kind,
            report_id=report.report_id,
            policy=policy,
            resource=case.policy.target,
            registered_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(seconds=expires_after),
        )
        for index, report in enumerate(saved)
    )
    author = case.metric.payload.children[0].binding
    scheduler = SchedulerServices(
        SchedulerPolicy(
            recipe_version="digest-fixture.v1",
            workflows=(
                WorkflowRegistration(
                    workflow_name=author.workflow_name,
                    workflow_version=author.workflow_version,
                    queue_name="unused-digest-fixture",
                    application_name="unused-digest-fixture",
                ),
            ),
        ),
        catalog,
        artifacts,
        freshness,
        FixtureIdentities(),
        FixtureResources(),
    )
    reader = NativeFactReader(
        NativeFactServices(catalog, artifacts, freshness, scheduler, case.policy.target, registered)
    )
    legacy = NativeNotificationFactLoader(catalog, artifacts, freshness)
    drafts = QualifiedNotificationDraftStore(
        factory,
        QualifiedNotificationFactAdapter(legacy, reader),
        case.drafts.recipients,
        policy=policy,
    )
    cases = []
    for registration in registered:
        event = await NativeFactEmitter(factory, reader).emit(
            owner_scope(),
            identity(OWNER),
            DigestSelector(company_id=COMPANY, schedule=registration.schedule),
        )
        assert event is not None, "Actual clock must be in its registered post09 digest window"
        draft = await drafts.publish_event(control(), identity(OWNER), event.event_id)
        cases.append(
            replace(
                case,
                drafts=drafts,
                selection=case.selection.model_copy(update={"draft_id": draft.draft_id}),
                preparation=ManagedNotificationPreparation(
                    factory, drafts, catalog, artifacts, freshness, policy=case.policy
                ),
                effects=ManagedNotificationEffectStore(
                    factory, drafts, catalog, artifacts, freshness, policy=case.policy
                ),
            )
        )
    return replace(
        case, drafts=drafts, preparation=cases[0].preparation, effects=cases[0].effects
    ), tuple(cases)
