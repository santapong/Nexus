"""Pure fixed notification runtime composition; no credential, queue, SDK or HTTP activation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID

from pydantic import TypeAdapter

from nexus.company.management.base import Symbol
from nexus.company.management.scheduling_contracts import WorkflowRegistration
from nexus.company.management.scheduling_support import SchedulerServices
from nexus.company.notifications.managed_effects import ManagedNotificationEffectStore
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.worker_dispatch import AuthenticatedManagedNotificationDispatcher
from nexus.company.notifications.worker_services import NotificationWorkerServices
from nexus.execution.runtime_store import ExecutionStore

NOTIFICATION_WORKFLOW = "internal.owner-notification"
NOTIFICATION_VERSION = "v1"
NOTIFICATION_QUEUE = "nexus.notifications.v1"
NOTIFICATION_APPLICATION = "nexus-owner-notifications"
_UNAVAILABLE = "Notification durable worker services are unavailable"


def notification_workflow_registration() -> WorkflowRegistration:
    """Return fixed server ABI metadata; this registers no work or queue."""
    return WorkflowRegistration(
        workflow_name=NOTIFICATION_WORKFLOW,
        workflow_version=NOTIFICATION_VERSION,
        queue_name=NOTIFICATION_QUEUE,
        application_name=NOTIFICATION_APPLICATION,
    )


@dataclass(frozen=True, slots=True)
class NotificationDispatchWorkerServices:
    """Exact process dependencies stay outside the portable command and cannot refill work."""

    reads: NotificationWorkerServices
    execution: ExecutionStore
    dispatcher: AuthenticatedManagedNotificationDispatcher
    scheduler: SchedulerServices
    worker_id: UUID
    executor_id: str = "nexus-owner-notifications-v1-local"
    lease_ttl_seconds: int = 60
    enabled: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.enabled) is not bool
            or type(self.lease_ttl_seconds) is not int
            or not 1 <= self.lease_ttl_seconds <= 300
            or not isinstance(self.worker_id, UUID)
            or TypeAdapter(Symbol).validate_python(self.executor_id) != self.executor_id
            or not isinstance(self.reads, NotificationWorkerServices)
            or not isinstance(self.execution, ExecutionStore)
            or not isinstance(self.dispatcher, AuthenticatedManagedNotificationDispatcher)
            or not isinstance(self.scheduler, SchedulerServices)
        ):
            raise NotificationUnavailableError(_UNAVAILABLE)
        self._require_dependencies()

    def _require_dependencies(self) -> None:
        # Revalidate the current mutable dependencies through the existing pure
        # read-service constructor, without opening a file, credential or database.
        replace(self.reads)
        facts, factory = self.reads.facts, self.reads.factory
        effects = self.dispatcher.managed_effects
        if not isinstance(effects, ManagedNotificationEffectStore):
            raise NotificationUnavailableError(_UNAVAILABLE)
        preparation = effects.preparation
        if (
            self.execution._factory is not factory
            or self.execution._management_catalog != facts.catalog
            or self.execution._management_artifacts is not facts.artifacts
            or self.execution._management_freshness is not facts.freshness
            or effects._factory is not factory
            or effects._management_catalog != facts.catalog
            or effects._management_artifacts is not facts.artifacts
            or effects._management_freshness is not facts.freshness
            or self.dispatcher.factory is not factory
            or self.dispatcher.effects is not effects
            or self.dispatcher.drafts is not self.reads.drafts
            or preparation.factory is not factory
            or preparation.drafts is not self.reads.drafts
            or preparation.catalog != facts.catalog
            or preparation.artifacts is not facts.artifacts
            or preparation.freshness is not facts.freshness
            or preparation.policy != self.reads.preparation.policy
            or self.dispatcher.target != preparation.policy.target
            or self.dispatcher.resource_symbol != preparation.policy.resource_symbol
            or self.scheduler.catalog != facts.catalog
            or self.scheduler.artifacts is not facts.artifacts
            or self.scheduler.freshness is not facts.freshness
            or self.scheduler.policy.max_tasks != 1
            or self.scheduler.policy.workflows != (notification_workflow_registration(),)
        ):
            raise NotificationUnavailableError(_UNAVAILABLE)

    def require_enabled(self) -> None:
        """Explicit process enablement still grants no approval, hold, lease or provider permit."""
        if self.enabled is not True or self.dispatcher.worker_enabled is not True:
            raise NotificationUnavailableError(_UNAVAILABLE)
        self._require_dependencies()
        self.dispatcher.configuration.require_configured()
