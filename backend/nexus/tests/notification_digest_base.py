"""Actual public initial digest sender plan; synthetic protected data and offline model only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.generated_artifact_store import GeneratedArtifactPublisher
from nexus.company.management.metric_contracts import MetricObservationRequest
from nexus.company.management.metric_store import MetricStore
from nexus.company.management.native_report_producer import NativeReportProducer
from nexus.company.management.native_report_validator import NativeReportValidator
from nexus.company.management.operating_report_store import OperatingReportStore
from nexus.company.management.report_artifact_reader import ReportArtifactReader
from nexus.company.management.report_inputs import PersistentReportInputLoader
from nexus.company.management.revision_store import plan_reference
from nexus.company.notifications.contracts import NotificationPolicy, OwnerRecipientPolicy
from nexus.company.notifications.draft_store import NotificationDraftStore
from nexus.company.notifications.managed_contracts import (
    NativeNotificationSelection,
    NotificationPreparationPolicy,
)
from nexus.company.notifications.managed_effects import ManagedNotificationEffectStore
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.company.notifications.native_loader import NativeNotificationFactLoader
from nexus.company.notifications.recipient_registry import (
    FileOwnerRecipients,
    RecipientRegistryFile,
)
from nexus.execution.effect_store import EffectStore
from nexus.execution.runtime_store import ExecutionStore
from nexus.tests.integration.test_company_directory import COMPANY, OWNER, control
from nexus.tests.integration.test_company_execution_store import identity
from nexus.tests.integration.test_company_notification_drafts import acceptance_event
from nexus.tests.metric_fixture import MetricScenario, accept_report
from nexus.tests.metric_plan_fixture import declared_metric_plan
from nexus.tests.notification_digest_plan import digest_sender_plan
from nexus.tests.notification_managed_fixture import ManagedNotificationCase


async def configured_digest_base(
    factory: async_sessionmaker[AsyncSession], root: Path
) -> ManagedNotificationCase:
    """Public native fixture setup is kept together; no operative rows are raw SQL seeded."""
    plans, payload, rules, policies, retriever, blobs, previous = await declared_metric_plan(
        factory, root
    )
    plans, payload, approved, target = await digest_sender_plan(
        factory, payload, previous, plans.catalog, plans
    )
    artifacts, freshness = (
        BoundedArtifactReader(factory, blobs),
        RegisteredSourceFreshness(factory, policies),
    )
    reports = OperatingReportStore(factory, plans.catalog, artifacts, freshness)
    inputs = PersistentReportInputLoader(
        factory, ReportArtifactReader(retriever, artifacts), reports, source_policies=policies
    )
    producer = NativeReportProducer(factory, reports, inputs)
    publisher = GeneratedArtifactPublisher(
        factory,
        blobs,
        plans.catalog,
        artifacts,
        policies,
        NativeReportValidator(producer),
        rules=rules,
    )
    execution = ExecutionStore(
        factory,
        management_catalog=plans.catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
    )
    effects = EffectStore(
        factory,
        management_catalog=plans.catalog,
        management_artifacts=artifacts,
        management_freshness=freshness,
    )
    metric = MetricScenario(
        MetricStore(factory, plans.catalog, artifacts, freshness),
        MetricObservationRequest(
            company_id=COMPANY,
            observation_id=uuid4(),
            goal=payload.goal,
            plan=plan_reference(approved),
            metric_id="unused-fixture-selector",
            task_ids=(payload.children[0].binding.task_id,),
        ),
        payload,
        publisher,
        producer,
        execution,
        effects,
        retriever,
    )
    await accept_report(factory, metric)
    now = datetime.now(UTC)
    path = root / "synthetic-managed-recipient.json"
    path.write_text(
        RecipientRegistryFile(
            policies=(
                OwnerRecipientPolicy(
                    company_id=COMPANY,
                    owner_id=OWNER,
                    policy_id=uuid4(),
                    version="managed-conformance.v1",
                    sender="system@example.invalid",
                    recipient="owner@example.invalid",
                    registered_at=now - timedelta(minutes=1),
                    expires_at=now + timedelta(hours=1),
                ),
            )
        ).model_dump_json()
    )
    path.chmod(0o600)
    drafts = NotificationDraftStore(
        factory,
        NativeNotificationFactLoader(plans.catalog, artifacts, freshness),
        FileOwnerRecipients(path),
        policy=NotificationPolicy(enabled=True, major_completion_task_ids=metric.request.task_ids),
    )
    event = await acceptance_event(factory)
    draft = await drafts.publish_event(control(), identity(OWNER), event.event_id)
    selection = NativeNotificationSelection(
        company_id=COMPANY,
        draft_id=draft.draft_id,
        sender_task_id=payload.children[-1].binding.task_id,
        plan=plan_reference(approved),
    )
    policy = NotificationPreparationPolicy(
        enabled=True, target=target, resource_symbol="owner.notifications"
    )
    preparation = ManagedNotificationPreparation(
        factory, drafts, plans.catalog, artifacts, freshness, policy=policy
    )
    managed_effects = ManagedNotificationEffectStore(
        factory, drafts, plans.catalog, artifacts, freshness, policy=policy
    )
    return ManagedNotificationCase(
        drafts,
        metric,
        plans,
        selection,
        policy,
        preparation,
        execution,
        managed_effects,
        plan_reference(previous),
    )
