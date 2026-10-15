"""Per-operation final mixed dispatcher and pre-request check; no retry or shared guard state."""

from datetime import UTC, datetime
from uuid import UUID

from nexus.company.notifications.dispatch_store import NotificationTransportConfiguration
from nexus.company.notifications.mixed_worker_intent import MixedCredentialNotificationIntentCheck
from nexus.company.notifications.native_facts import NotificationUnavailableError
from nexus.company.notifications.worker_dispatch import AuthenticatedManagedNotificationDispatcher
from nexus.company.notifications.worker_guard import NotificationOperationGuard
from nexus.company.notifications.worker_identity import AuthenticatedWorkerIdentity
from nexus.company.notifications.worker_intent import CredentialNotificationIntentCheck
from nexus.company.notifications.worker_services import NotificationWorkerServices
from nexus.company.notifications.worker_transport import CredentialedResendTransport
from nexus.execution.runtime_contracts import ExecutionLease


class MixedCredentialedResendTransport(CredentialedResendTransport):
    """Concrete entire native/config window closure immediately before the existing HTTP seam."""

    def __init__(
        self,
        check: MixedCredentialNotificationIntentCheck,
        configuration: NotificationTransportConfiguration,
    ) -> None:
        if type(check) is not MixedCredentialNotificationIntentCheck or check.draft is None:
            raise NotificationUnavailableError("Mixed transport native check is unavailable")
        self.check = check
        super().__init__(
            check.draft.recipient_policy,
            configuration.api_key,
            check.witness,
            enabled=True,
            transport=configuration.http_transport,
        )

    async def _request(
        self, method: str, path: str, *, payload: bytes | None = None, key: str | None = None
    ) -> tuple[int, bytes]:
        self.check.validate_time(datetime.now(UTC))
        return await super()._request(method, path, payload=payload, key=key)


class MixedNotificationDispatcher(AuthenticatedManagedNotificationDispatcher):
    """Final concrete one-context wrapper; base dispatch/replay/control flow remains unchanged."""

    def __init__(
        self,
        original: AuthenticatedManagedNotificationDispatcher,
        reads: NotificationWorkerServices,
        guard: NotificationOperationGuard,
    ) -> None:
        if (
            type(original) is not AuthenticatedManagedNotificationDispatcher
            or type(reads) is not NotificationWorkerServices
            or type(guard) is not NotificationOperationGuard
        ):
            raise NotificationUnavailableError("Mixed dispatcher composition is unavailable")
        if (
            original.factory is not reads.factory
            or original.drafts is not reads.drafts
            or original.managed_effects.preparation.catalog != reads.facts.catalog
            or original.managed_effects.preparation.artifacts is not reads.facts.artifacts
            or original.managed_effects.preparation.freshness is not reads.facts.freshness
            or guard.reader is not reads.registrations
        ):
            raise NotificationUnavailableError("Mixed dispatcher source composition differs")
        self.reads, self.operation_guard = reads, guard
        super().__init__(
            original.factory,
            original.drafts,
            original.managed_effects,
            configuration=original.configuration,
            enabled=original.worker_enabled,
        )

    def _intent_check(
        self,
        lease: ExecutionLease,
        witness: AuthenticatedWorkerIdentity,
        draft_id: UUID,
        action_id: UUID,
    ) -> CredentialNotificationIntentCheck:
        return MixedCredentialNotificationIntentCheck(
            lease,
            witness,
            draft_id,
            self.drafts,
            self.target,
            self.resource_symbol,
            action_id=action_id,
            operation_guard=self.operation_guard,
            reads=self.reads,
        )

    def _transport(self, check: CredentialNotificationIntentCheck) -> CredentialedResendTransport:
        if (
            type(check) is not MixedCredentialNotificationIntentCheck
            or check.reads is not self.reads
            or check.operation_guard is not self.operation_guard
        ):
            raise NotificationUnavailableError("Mixed final transport check differs")
        return MixedCredentialedResendTransport(check, self.configuration)
