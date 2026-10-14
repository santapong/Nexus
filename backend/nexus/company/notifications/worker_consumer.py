"""Per-operation same-session sender closure at the inherited qualified cursor final clock."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.company.access import CompanyControlScope, VerifiedIdentity
from nexus.company.brain.events import OutboxEvent
from nexus.company.notifications.contracts import OwnerRecipientPolicy
from nexus.company.notifications.qualified_consumer import (
    QualifiedNotificationConsumer,
    _QualifiedHandler,
)
from nexus.company.notifications.qualified_store import QualifiedNotificationDraftStore
from nexus.company.notifications.worker_config import WorkerConfigurationError
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.notifications.worker_services import (
    NotificationWorkerServices,
    WorkerSenderAdmission,
)

_UNAVAILABLE = "Notification worker consumer qualification is unavailable"


class WorkerSenderFinalGuard(NotificationOperationGuard):
    """Fresh handler-owned captures narrow final time; the immutable base witness is retained."""

    __slots__ = ("_admissions", "_services", "base_guard")
    _admissions: list[WorkerSenderAdmission]
    _services: NotificationWorkerServices
    base_guard: NotificationOperationGuard

    def __init__(
        self,
        guard: NotificationOperationGuard,
        services: NotificationWorkerServices,
    ) -> None:
        if not isinstance(guard, NotificationOperationGuard) or not isinstance(
            services, NotificationWorkerServices
        ):
            raise WorkerConfigurationError(_UNAVAILABLE)
        super().__init__(guard.witness, guard.snapshot, guard.reader)
        object.__setattr__(self, "_services", services)
        object.__setattr__(self, "_admissions", [])
        object.__setattr__(self, "base_guard", guard)

    def capture(self, admission: WorkerSenderAdmission) -> None:
        if not isinstance(admission, WorkerSenderAdmission) or len(self._admissions) >= 33:
            raise WorkerConfigurationError(_UNAVAILABLE)
        self._admissions.append(admission)

    def require_time(self, now: datetime) -> None:
        super().require_time(now)
        self._services.require_registration(self.snapshot)
        if not self._admissions:
            raise WorkerConfigurationError(_UNAVAILABLE)
        for admission in self._admissions:
            admission.require_time(self._services, now)


class WorkerQualifiedHandler(_QualifiedHandler):
    def __init__(
        self,
        store: QualifiedNotificationDraftStore,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        recipient: OwnerRecipientPolicy,
        guard: WorkerSenderFinalGuard,
        services: NotificationWorkerServices,
    ) -> None:
        super().__init__(store, scope, identity, recipient, guard)
        self.final_guard, self.services = guard, services

    async def apply(self, session: AsyncSession, event: OutboxEvent) -> None:
        control = await self.control(session)
        admitted = await self.services.require_sender_locked(
            session, control, self.scope, self.final_guard.base_guard
        )
        self.final_guard.capture(admitted)
        await super().apply(session, event)

    async def finalize(self, session: AsyncSession) -> None:
        control = await self.control(session)
        admitted = await self.services.require_sender_locked(
            session, control, self.scope, self.final_guard.base_guard
        )
        self.final_guard.capture(admitted)
        await super().finalize(session)


class WorkerNotificationConsumer(QualifiedNotificationConsumer):
    def __init__(
        self,
        store: QualifiedNotificationDraftStore,
        *,
        consumer: str,
        recipe_version: str,
        operation_guard: NotificationOperationGuard,
        services: NotificationWorkerServices,
    ) -> None:
        super().__init__(
            store, consumer=consumer, recipe_version=recipe_version, operation_guard=operation_guard
        )
        self.services = services

    def _handler(
        self,
        scope: CompanyControlScope,
        identity: VerifiedIdentity,
        recipient: OwnerRecipientPolicy,
    ) -> WorkerQualifiedHandler:
        if self.operation_guard is None:
            raise WorkerConfigurationError(_UNAVAILABLE)
        guard = WorkerSenderFinalGuard(self.operation_guard, self.services)
        return WorkerQualifiedHandler(self.store, scope, identity, recipient, guard, self.services)
