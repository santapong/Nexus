"""Concrete mixed classes with synthetic sealed credential; no native SQL or HTTP proof."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.company.brain.artifact_store import BoundedArtifactReader
from nexus.company.brain.native_fact_reader import NativeFactReader
from nexus.company.brain.native_fact_services import NativeFactServices
from nexus.company.management.acceptance_freshness import RegisteredSourceFreshness
from nexus.company.management.canonical import canonical_sha256
from nexus.company.management.lifecycle import PlanRevisionRef
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.company.notifications.contracts import NotificationPolicy
from nexus.company.notifications.managed_admission import notification_action_id
from nexus.company.notifications.managed_contracts import NotificationPreparationPolicy
from nexus.company.notifications.managed_effects import ManagedNotificationEffectStore
from nexus.company.notifications.managed_preparation import ManagedNotificationPreparation
from nexus.company.notifications.mixed_worker_intent import MixedCredentialNotificationIntentCheck
from nexus.company.notifications.native_loader import NativeNotificationFactLoader
from nexus.company.notifications.qualified_adapter import QualifiedNotificationFactAdapter
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.company.notifications.recipient_registry import RegisteredOwnerRecipients
from nexus.company.notifications.worker_config import FileNotificationWorkerRegistration
from nexus.company.notifications.worker_contracts import (
    NotificationWorkerConfiguration,
    NotificationWorkerRegistration,
    NotificationWorkerRegistrationFile,
)
from nexus.company.notifications.worker_dispatch import AuthenticatedManagedNotificationDispatcher
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.notifications.worker_identity import NotificationWorkerIdentities
from nexus.company.notifications.worker_services import NotificationWorkerServices
from nexus.execution.runtime_contracts import ExecutionLease
from nexus.tests.unit.strategy_transition_observation_fixture import TransitionCase, transition_case


@dataclass(frozen=True)
class MixedCase:
    reads: NotificationWorkerServices
    guard: NotificationOperationGuard
    lease: ExecutionLease
    draft_id: UUID
    action_id: UUID
    original: AuthenticatedManagedNotificationDispatcher
    check: MixedCredentialNotificationIntentCheck
    now: datetime
    path: Path
    data: TransitionCase


def mixed_case(root: Path) -> MixedCase:
    # One >50-line linked configuration fixture; bodies/source/slot gates remain explicitly mocked.
    case = transition_case(2)
    catalog, now = case.catalog, case.now
    admission = catalog.cycle_admission
    assert admission is not None
    sender = admission.slots[-1].child.binding
    factory = cast(async_sessionmaker[AsyncSession], MagicMock(spec=async_sessionmaker))
    artifacts = MagicMock(spec=BoundedArtifactReader)
    artifacts.factory = factory
    freshness = MagicMock(spec=RegisteredSourceFreshness)
    freshness._factory = factory
    scheduler = MagicMock(spec=SchedulerServices)
    scheduler.catalog = catalog
    target = catalog.notification_profiles[0].target_resource
    facts = NativeFactServices(catalog, artifacts, freshness, scheduler, target)
    drafts = QualifiedNotificationDraftStore(
        factory,
        QualifiedNotificationFactAdapter(
            NativeNotificationFactLoader(catalog, artifacts, freshness), NativeFactReader(facts)
        ),
        MagicMock(spec=RegisteredOwnerRecipients),
        policy=NotificationPolicy(enabled=True),
    )
    preparation = ManagedNotificationPreparation(
        factory,
        drafts,
        catalog,
        artifacts,
        freshness,
        policy=NotificationPreparationPolicy(
            enabled=True, target=target, resource_symbol=admission.slots[-1].tool.resource
        ),
    )
    path = root / "mixed-registration.json"
    registration_reader = FileNotificationWorkerRegistration(path)
    reads = NotificationWorkerServices(
        factory, NotificationWorkerIdentities(), registration_reader, facts, drafts, preparation
    )
    digest = canonical_sha256(case.payload)
    reference = PlanRevisionRef(
        company_id=sender.company_id,
        plan_id=case.payload.plan.plan_id,
        plan_revision_id=uuid5(case.payload.plan.plan_id, "plan:2:" + digest),
        revision=2,
        sha256=digest,
    )
    registration = NotificationWorkerRegistration(
        company_id=sender.company_id,
        workspace_id=sender.workspace_id,
        registration_id=UUID(int=1900),
        sender=sender,
        plan=reference,
        catalog_sha256=canonical_sha256(catalog),
        notification_policy_sha256=canonical_sha256(drafts.policy),
        preparation_policy_sha256=canonical_sha256(preparation.policy),
        registered_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(seconds=120),
    )
    path.write_text(
        NotificationWorkerRegistrationFile(
            registration=registration, configuration=NotificationWorkerConfiguration(enabled=True)
        ).model_dump_json()
    )
    path.chmod(0o600)
    witness = case.proof.initial.sources.credential
    guard = NotificationOperationGuard(witness, registration_reader.snapshot(), registration_reader)
    lease = ExecutionLease(
        company_id=sender.company_id,
        task_id=sender.task_id,
        trace_id=sender.trace_id,
        actor_id=sender.actor_id,
        workspace_id=sender.workspace_id,
        run_id=sender.run_id,
        workflow_version="v1",
        segment_id=UUID(int=1901),
        worker_id=UUID(int=1902),
        fence=2,
        expires_at=now + timedelta(seconds=60),
        mode="execute",
    )
    draft = UUID(int=1903)
    action = notification_action_id(reference, sender.task_id, draft)
    effects = ManagedNotificationEffectStore(
        factory, drafts, catalog, artifacts, freshness, policy=preparation.policy
    )
    original = AuthenticatedManagedNotificationDispatcher(factory, drafts, effects, enabled=True)
    check = MixedCredentialNotificationIntentCheck(
        lease,
        witness,
        draft,
        drafts,
        target,
        preparation.policy.resource_symbol,
        action_id=action,
        operation_guard=guard,
        reads=reads,
    )
    return MixedCase(reads, guard, lease, draft, action, original, check, now, path, case)
