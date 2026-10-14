"""Pure fixed runtime composition; no file, database, SDK or transport activation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

from nexus.company.management.scheduling_contracts import SchedulerPolicy, WorkflowRegistration
from nexus.company.management.scheduling_support import (
    SchedulerIdentities,
    SchedulerResources,
    SchedulerServices,
)
from nexus.company.notifications.managed_effects import ManagedNotificationEffectStore
from nexus.company.notifications.worker_dispatch import AuthenticatedManagedNotificationDispatcher
from nexus.execution.notification_worker_services import NotificationDispatchWorkerServices
from nexus.execution.runtime_store import ExecutionStore
from nexus.tests.unit.test_company_notification_worker_services import services


def dispatch_services(tmp_path: Path) -> NotificationDispatchWorkerServices:
    reads = services(tmp_path)
    effects = ManagedNotificationEffectStore(
        reads.factory,
        reads.drafts,
        reads.facts.catalog,
        reads.facts.artifacts,
        reads.facts.freshness,
        policy=reads.preparation.policy,
    )
    dispatcher = AuthenticatedManagedNotificationDispatcher(reads.factory, reads.drafts, effects)
    execution = ExecutionStore(
        reads.factory,
        management_catalog=reads.facts.catalog,
        management_artifacts=reads.facts.artifacts,
        management_freshness=reads.facts.freshness,
    )
    scheduler = SchedulerServices(
        SchedulerPolicy(
            recipe_version="notification-dispatch-v1",
            max_tasks=1,
            workflows=(
                WorkflowRegistration(
                    workflow_name="internal.owner-notification",
                    workflow_version="v1",
                    queue_name="nexus.notifications.v1",
                    application_name="nexus-owner-notifications",
                ),
            ),
        ),
        reads.facts.catalog,
        reads.facts.artifacts,
        reads.facts.freshness,
        MagicMock(spec=SchedulerIdentities),
        MagicMock(spec=SchedulerResources),
    )
    return NotificationDispatchWorkerServices(
        reads,
        execution,
        dispatcher,
        scheduler,
        worker_id=UUID(int=820),
    )
