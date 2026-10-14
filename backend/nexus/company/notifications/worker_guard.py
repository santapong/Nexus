"""Concrete process-only credential/config deadline guard; no arbitrary callback or authority."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from nexus.company.access import VerifiedIdentity
from nexus.company.notifications.worker_config import (
    FileNotificationWorkerRegistration,
    WorkerConfigurationError,
    WorkerRegistrationSnapshot,
)
from nexus.company.notifications.worker_contracts import NotificationWorkerRegistration
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity

_UNAVAILABLE = "Notification worker operation is unavailable"


@dataclass(frozen=True, slots=True, init=False)
class NotificationOperationGuard:
    """Observed time/pins narrow one configured operation; native current permission is separate."""

    witness: AuthenticatedWorkerIdentity
    snapshot: WorkerRegistrationSnapshot
    reader: FileNotificationWorkerRegistration

    def __init__(
        self,
        witness: AuthenticatedWorkerIdentity,
        snapshot: WorkerRegistrationSnapshot,
        reader: FileNotificationWorkerRegistration,
    ) -> None:
        if (
            not isinstance(witness, AuthenticatedWorkerIdentity)
            or not isinstance(snapshot, WorkerRegistrationSnapshot)
            or not isinstance(reader, FileNotificationWorkerRegistration)
        ):
            raise WorkerConfigurationError(_UNAVAILABLE)
        reader.require_current(snapshot)
        registration = snapshot.value.registration
        if (witness.identity.principal_id, witness.identity.workspace_id) != (
            registration.sender.actor_id,
            registration.workspace_id,
        ):
            raise WorkerConfigurationError(_UNAVAILABLE)
        object.__setattr__(self, "witness", witness)
        object.__setattr__(self, "snapshot", snapshot)
        object.__setattr__(self, "reader", reader)

    @property
    def registration(self) -> NotificationWorkerRegistration:
        """Return descriptive exact original configuration, never a native registration proof."""
        return self.snapshot.value.registration

    def require_identity(self, identity: VerifiedIdentity) -> None:
        """A same-name or bare owner ID cannot replace the actual sealed credential identity."""
        if not isinstance(identity, VerifiedIdentity) or identity != self.witness.identity:
            raise WorkerConfigurationError(_UNAVAILABLE)

    def require_company(self, company_id: UUID) -> None:
        """Exact configured company metadata; actual current owner remains a native DB check."""
        if company_id != self.registration.company_id:
            raise WorkerConfigurationError(_UNAVAILABLE)

    def require_time(self, now: datetime) -> None:
        """Use only the native method's actual final aware DB clock, with synchronous pins."""
        self.witness.require_time(now)
        if (
            not self.snapshot.value.configuration.enabled
            or not self.registration.registered_at <= now < self.registration.expires_at
        ):
            raise WorkerConfigurationError(_UNAVAILABLE)
        self.reader.require_current(self.snapshot)
